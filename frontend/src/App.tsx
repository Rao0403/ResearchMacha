import { lazy, Suspense } from "react";
import { BookOpen, Files, Library, Search } from "lucide-react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";

import { BatchSummaryPage } from "./pages/BatchSummaryPage";
import { LibraryPage } from "./pages/LibraryPage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { ResearchWorkflowPage } from "./pages/ResearchWorkflowPage";
import { SearchPage } from "./pages/SearchPage";

const ReaderPage = lazy(() => import("./pages/ReaderPage").then((module) => ({ default: module.ReaderPage })));

export function App() {
  const location = useLocation();
  const isWideWorkspace = location.pathname === "/reader"
    || location.pathname.startsWith("/reader/")
    || location.pathname.startsWith("/papers/")
    || location.pathname === "/batch-summary";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to workspace</a>
      <aside className="sidebar" aria-label="Application navigation">
        <NavLink to="/" className="brand-lockup" aria-label="ResearchMacha home">
          <span className="brand-mark" aria-hidden="true">RM</span>
          <span className="brand-name">ResearchMacha</span>
        </NavLink>
        <nav className="nav-links" aria-label="Primary navigation">
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)} aria-label="Research">
            <span className="nav-icon">
              <Search size={17} />
            </span>
            <span className="nav-label">Research</span>
          </NavLink>
          <NavLink to="/reader" className={({ isActive }) => navClass(isActive)} aria-label="Reader">
            <span className="nav-icon">
              <BookOpen size={17} />
            </span>
            <span className="nav-label">Reader</span>
          </NavLink>
          <NavLink to="/batch-summary" className={({ isActive }) => navClass(isActive)} aria-label="Compare">
            <span className="nav-icon">
              <Files size={17} />
            </span>
            <span className="nav-label">Compare</span>
          </NavLink>
          <NavLink to="/library" className={({ isActive }) => navClass(isActive)} aria-label="Library">
            <span className="nav-icon">
              <Library size={17} />
            </span>
            <span className="nav-label">Library</span>
          </NavLink>
        </nav>
      </aside>

      <main id="main-content" className={`page-frame${isWideWorkspace ? " page-frame-wide" : ""}`} tabIndex={-1}>
        <Suspense fallback={<p className="shell-loading" role="status">Loading workspace...</p>}>
          <Routes>
            <Route path="/" element={<ResearchWorkflowPage />} />
            <Route path="/reader" element={<ReaderPage />} />
            <Route path="/reader/:paperId" element={<ReaderPage />} />
            <Route path="/batch-summary" element={<BatchSummaryPage />} />
            <Route path="/library" element={<LibraryPage />} />
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
