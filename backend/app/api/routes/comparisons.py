from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.paper import Comparison, Job, Paper
from app.services import comparisons as service

router=APIRouter()

class ComparisonInput(BaseModel):
    name: str = Field(default="Paper comparison",min_length=1,max_length=255)
    goal: str = Field(min_length=3,max_length=2000)
    paper_ids: list[str] = Field(min_length=2,max_length=10)

class ComparisonCreate(ComparisonInput):
    request_id: str = Field(min_length=1,max_length=64)

class ComparisonEdit(ComparisonInput):
    version: int = Field(ge=0)

class ComparisonGenerate(BaseModel):
    request_id: str = Field(min_length=1,max_length=64)
    version: int = Field(ge=0)

@router.get("/comparisons")
def list_comparisons(db:Session=Depends(get_db)):
    return [service.serialize_comparison(db,row,include_result=False) for row in db.query(Comparison).order_by(Comparison.updated_at.desc()).all()]

@router.post("/comparisons")
def create_comparison(payload:ComparisonCreate,db:Session=Depends(get_db)):
    return service.serialize_comparison(db,service.create_comparison(db,name=payload.name,goal=payload.goal,ids=payload.paper_ids,request_id=payload.request_id))

@router.post("/comparisons/upload")
def upload_comparison(
    files:list[UploadFile]=File(...), name:str=Form("Paper comparison",min_length=1,max_length=255),
    goal:str=Form(...,min_length=3,max_length=2000), request_id:str=Form(...,min_length=1,max_length=64),
    db:Session=Depends(get_db),
):
    if not name.strip() or len(goal.strip()) < 3:
        raise HTTPException(422,"Provide a name and comparison goal")
    existing=db.query(Comparison).filter_by(creation_key=request_id).one_or_none()
    if existing:
        if existing.goal != goal: raise HTTPException(409,"Request ID belongs to another comparison")
        service.generate_comparison(db,existing.id,request_id,existing.version)
        return service.serialize_comparison(db,service.get_comparison(db,existing.id))
    if not 2 <= len(files) <= 10: raise HTTPException(422,"Choose 2 to 10 PDFs")
    from app.api.routes.papers import batch_upload_papers
    uploaded=batch_upload_papers(files=files,db=db)
    row=service.create_comparison(db,name=name,goal=goal,ids=[item.paper.id for item in uploaded.items],request_id=request_id)
    return service.serialize_comparison(db,row)

@router.get("/comparisons/{ident}/status")
def comparison_status(ident:str,db:Session=Depends(get_db)):
    row=service.get_comparison(db,ident)
    return {"id":row.id,"status":row.status,"generation":row.generation,"updated_at":row.updated_at,
            "ready_count":sum(l.paper.status in {"ready","degraded"} for l in row.papers)}

@router.get("/comparisons/{ident}")
def comparison_detail(ident:str,db:Session=Depends(get_db)):
    return service.serialize_comparison(db,service.get_comparison(db,ident))

@router.patch("/comparisons/{ident}")
def edit_comparison(ident:str,payload:ComparisonEdit,db:Session=Depends(get_db)):
    return service.serialize_comparison(db,service.update_comparison(db,ident,name=payload.name,goal=payload.goal,ids=payload.paper_ids,version=payload.version))

@router.post("/comparisons/{ident}/generate")
def generate_comparison(ident:str,payload:ComparisonGenerate,db:Session=Depends(get_db)):
    service.generate_comparison(db,ident,payload.request_id,payload.version)
    return service.serialize_comparison(db,service.get_comparison(db,ident))

@router.post("/comparisons/{ident}/retry-paper/{paper_id}")
def retry_comparison_paper(ident:str,paper_id:str,db:Session=Depends(get_db)):
    from app.services.research import retry_job
    row=service.get_comparison(db,ident)
    if paper_id not in service.paper_ids(row): raise HTTPException(404,"Paper is not in this comparison")
    job=db.query(Job).filter_by(paper_id=paper_id,job_type="analysis").order_by(Job.created_at.desc()).first()
    if job is None: raise HTTPException(409,"No analysis job is available to retry")
    retry_job(db,job.id)
    paper=db.get(Paper,paper_id)
    if paper.status=="failed": paper.status="queued";db.commit()
    service.reconcile_comparison(db,ident)
    return service.serialize_comparison(db,service.get_comparison(db,ident))
