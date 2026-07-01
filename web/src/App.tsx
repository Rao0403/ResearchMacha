import { NavLink, Route, Routes } from "react-router-dom";

import { LibraryPage } from "./pages/LibraryPage";
import { PaperWorkspacePage } from "./pages/PaperWorkspacePage";
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
            Discover
          </NavLink>
          <NavLink to="/library" className={({ isActive }) => navClass(isActive)}>
            Library
          </NavLink>
        </nav>
        <div className="sidebar-note">
          <p>Summaries, highlighted evidence, and grounded chat for every paper you import.</p>
        </div>
      </aside>

      <main className="page-frame">
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/papers/:paperId" element={<PaperWorkspacePage />} />
        </Routes>
      </main>
    </div>
  );
}

function navClass(isActive: boolean) {
  return `nav-link${isActive ? " nav-link-active" : ""}`;
}

