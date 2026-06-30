import { useNavigate } from "react-router";

import { useSessionStore } from "../stores/sessionStore";

export default function Login() {
  const navigate = useNavigate();
  const setAccessToken = useSessionStore((state) => state.setAccessToken);

  const handleLogin = () => {
    setAccessToken("phase1-placeholder-token");
    navigate("/dashboard");
  };

  return (
    <main className="screen">
      <section className="panel">
        <p className="eyebrow">NexusMesh</p>
        <h1>Phase 1 Login Shell</h1>
        <p className="muted">
          JWT Auth API skeleton is ready on the backend. This page is the
          minimum frontend shell required by Phase 1.
        </p>
        <button className="primaryButton" onClick={handleLogin} type="button">
          Enter Dashboard
        </button>
      </section>
    </main>
  );
}
