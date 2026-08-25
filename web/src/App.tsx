import { lazy, Suspense } from "react";
import { BookOpen, Files, Search, Sparkles } from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";

import { BatchSummaryPage } from "./pages/BatchSummaryPage";
import { LibraryPage } from "./pages/LibraryPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { ResearchWorkflowPage } from "./pages/ResearchWorkflowPage";
import { SearchPage } from "./pages/SearchPage";

const ReaderPage = lazy(() => import("./pages/ReaderPage").then((module) => ({ default: module.ReaderPage })));

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div>
            <p className="eyebrow">Agentic research desk</p>
            <h1>ResearchMacha</h1>
          </div>
        </div>
        <nav className="nav-links">
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
            <span className="nav-icon">
              <Search size={17} />
            </span>
            <span>
              <strong>Research</strong>
              <small>Question to cited brief</small>
            </span>
          </NavLink>
          <NavLink to="/reader" className={({ isActive }) => navClass(isActive)}>
            <span className="nav-icon">
              <BookOpen size={17} />
            </span>
            <span>
              <strong>Reader</strong>
              <small>PDF notes and chat</small>
            </span>
          </NavLink>
          <NavLink to="/batch-summary" className={({ isActive }) => navClass(isActive)}>
            <span className="nav-icon">
              <Files size={17} />
            </span>
            <span>
              <strong>Batch Summary</strong>
              <small>Compare multiple papers</small>
            </span>
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <Sparkles size={18} />
          <strong>Local-first AI workbench</strong>
          <p>Question-driven paper discovery, cited synthesis, and reading support in one local workbench.</p>
        </div>
      </aside>

      <main className="page-frame">
        <Suspense fallback={<p className="status-note">Loading workspace...</p>}>
          <Routes>
            <Route path="/" element={<ResearchWorkflowPage />} />
            <Route path="/reader" element={<ReaderPage />} />
            <Route path="/reader/:paperId" element={<ReaderPage />} />
            <Route path="/batch-summary" element={<BatchSummaryPage />} />
            <Route path="/papers/:paperId" element={<ReaderPage />} />
            <Route path="/debug/projects" element={<ProjectListPage />} />
            <Route path="/debug/discover" element={<SearchPage />} />
            <Route path="/debug/library" element={<LibraryPage />} />
            <Route path="/debug/projects/:projectId" element={<ProjectWorkspacePage />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

function navClass(isActive: boolean) {
  return `nav-link${isActive ? " nav-link-active" : ""}`;
}
