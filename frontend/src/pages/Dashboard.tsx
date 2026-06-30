import { useSessionStore } from "../stores/sessionStore";

export default function Dashboard() {
  const accessToken = useSessionStore((state) => state.accessToken);

  return (
    <main className="screen">
      <section className="panel">
        <p className="eyebrow">Dashboard</p>
        <h1>NexusMesh Control Surface</h1>
        <p className="muted">
          React Flow canvas, timeline and log stream will be completed in later
          phases.
        </p>
        <pre className="tokenPreview">
          token: {accessToken ?? "not logged in"}
        </pre>
      </section>
    </main>
  );
}
