import pytest
from app.ai import AIProviderError, MockProvider
from app.models.paper import ResearchProject, Paper
from app.services import research
from app.services.provenance import brief_is_outdated
from test_workflow_reconciliation import workflow_database, seed_ready_project


def prepare(tmp_path, monkeypatch):
    engine, factory = workflow_database(tmp_path)
    project_id, paper_ids = seed_ready_project(factory)
    sources = [{"paper_id":paper_ids[0],"title":"Paper 0","summary":"Evidence", "chunks":[
        {"id":"source","page_start":3,"page_end":3,"text":"A measured result."}]}]
    monkeypatch.setattr(research,"build_paper_contexts",lambda project:sources)
    monkeypatch.setattr(research,"retrieve_memories",lambda *args,**kwargs:[])
    class Provider(MockProvider):
        def synthesize_collection(self,*args):
            output=super().synthesize_collection(*args);output.generation_mode="ai";output.warnings=[]
            return output
    monkeypatch.setattr(research,"get_ai_provider",lambda:Provider())
    return engine,factory,project_id,paper_ids[0]


def test_brief_records_sources_and_retains_them_after_failed_replacement(tmp_path,monkeypatch):
    engine,factory,project_id,paper_id=prepare(tmp_path,monkeypatch)
    with factory() as db:
        project=research.synthesize_project(db,project_id,expected_generation=0)
        original=project.synthesis_json
        assert original["artifact"]["papers"][0]["analysis_generation"]==1
        assert original["artifact"]["papers"][0]["chunk_ids"]==["source"]
        assert brief_is_outdated(project) is False
        project.synthesis_generation+=1; db.commit()
        class Failing:
            def synthesize_collection(self,*args):raise AIProviderError("Unavailable")
        monkeypatch.setattr(research,"get_ai_provider",lambda:Failing())
        project=research.synthesize_project(db,project_id,expected_generation=1)
        assert project.synthesis_json["artifact"]==original["artifact"]
        assert project.synthesis_json["executive_summary"]==original["executive_summary"]
        assert project.synthesis_json["generation_mode"]=="ai"
        assert project.synthesis_json["warnings"] and project.status=="degraded"
        assert brief_is_outdated(project) is True
    engine.dispose()


def test_concurrent_evidence_change_cannot_be_overwritten_by_stale_session(tmp_path,monkeypatch):
    engine,factory,project_id,_=prepare(tmp_path,monkeypatch)
    provider=research.get_ai_provider()
    class EditingProvider:
        def synthesize_collection(self,*args):
            with factory() as other:
                project=other.get(ResearchProject,project_id)
                project.synthesis_generation=1
                project.synthesis_json={"executive_summary":"Newer result"}
                other.commit()
            return provider.synthesize_collection(*args)
    monkeypatch.setattr(research,"get_ai_provider",lambda:EditingProvider())
    with factory() as db,pytest.raises(research.StaleSynthesisJob):
        research.synthesize_project(db,project_id,expected_generation=0)
    with factory() as db: assert db.get(ResearchProject,project_id).synthesis_json["executive_summary"]=="Newer result"
    engine.dispose()
