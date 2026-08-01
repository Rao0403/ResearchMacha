import { BookOpen, Files, Search } from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";

import { BatchSummaryPage } from "./pages/BatchSummaryPage";
import { LibraryPage } from "./pages/LibraryPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { ReaderPage } from "./pages/ReaderPage";
import { ResearchWorkflowPage } from "./pages/ResearchWorkflowPage";
import { SearchPage } from "./pages/SearchPage";

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <span className="brand-mark">RM</span>
          <div>
            <p className="eyebrow">Research desk</p>
            <h1>ResearchMacha</h1>
          </div>
        </div>
        <nav className="nav-links">
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
            <Search size={17} />
            Research
          </NavLink>
          <NavLink to="/reader" className={({ isActive }) => navClass(isActive)}>
            <BookOpen size={17} />
            Reader
          </NavLink>
          <NavLink to="/batch-summary" className={({ isActive }) => navClass(isActive)}>
            <Files size={17} />
            Batch Summary
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <BookOpen size={18} />
          <p>Question-driven paper discovery, cited synthesis, and reading support in one local workbench.</p>
        </div>
      </aside>

      <main className="page-frame">
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
      </main>
    </div>
  );
}

function navClass(isActive: boolean) {
  return `nav-link${isActive ? " nav-link-active" : ""}`;
}
