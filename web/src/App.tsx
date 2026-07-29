import { BookOpen, FolderKanban, Library, Search } from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";

import { LibraryPage } from "./pages/LibraryPage";
import { PaperWorkspacePage } from "./pages/PaperWorkspacePage";
import { ProjectListPage } from "./pages/ProjectListPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
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
            <FolderKanban size={17} />
            Projects
          </NavLink>
          <NavLink to="/discover" className={({ isActive }) => navClass(isActive)}>
            <Search size={17} />
            Discover
          </NavLink>
          <NavLink to="/library" className={({ isActive }) => navClass(isActive)}>
            <Library size={17} />
            Library
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <BookOpen size={18} />
          <p>Question-driven paper discovery, cited synthesis, and reading support in one local workbench.</p>
        </div>
      </aside>

      <main className="page-frame">
        <Routes>
          <Route path="/" element={<ProjectListPage />} />
          <Route path="/discover" element={<SearchPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/projects/:projectId" element={<ProjectWorkspacePage />} />
          <Route path="/papers/:paperId" element={<PaperWorkspacePage />} />
        </Routes>
      </main>
    </div>
  );
}

function navClass(isActive: boolean) {
  return `nav-link${isActive ? " nav-link-active" : ""}`;
}
