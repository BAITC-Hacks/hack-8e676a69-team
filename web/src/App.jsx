import { useState } from "react";

// ONE page, no router. A client-side router 404s on refresh under a static
// mount (StaticFiles serves index.html only at "/", not at every deep-link
// path), and a single state-driven page removes that entire class of bug.

export default function App() {
  const [view, setView] = useState("upload"); // 'upload' | 'processing' | 'result' | 'error'
  const [file, setFile] = useState(null);
  const [ticket, setTicket] = useState(null);
  const [error, setError] = useState(null);

  function reset() {
    setView("upload");
    setFile(null);
    setTicket(null);
    setError(null);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!file) return;
    setView("processing");

    const formData = new FormData();
    formData.append("file", file);

    try {
      // Relative URL only - absolute URLs / env vars must never be introduced,
      // vite's dev proxy and the prod static mount both rely on this being relative.
      const res = await fetch("/api/tickets", { method: "POST", body: formData });
      if (!res.ok) {
        throw new Error(`request failed: ${res.status}`);
      }
      const data = await res.json();
      setTicket(data);
      setView(data.status === "error" ? "error" : "result");
    } catch (err) {
      setError(String(err));
      setView("error");
    }
  }

  return (
    <div style={{ fontFamily: "sans-serif", maxWidth: 480, margin: "40px auto", padding: 16 }}>
      <h1>HackAlem</h1>

      {view === "upload" && (
        <form onSubmit={handleSubmit}>
          <input
            type="file"
            accept="image/*"
            onChange={(e) => setFile(e.target.files[0] ?? null)}
          />
          <div style={{ marginTop: 12 }}>
            <button type="submit" disabled={!file}>
              Submit
            </button>
          </div>
        </form>
      )}

      {view === "processing" && <p>Processing...</p>}

      {view === "result" && ticket && (
        <div>
          <p>Status: {ticket.status}</p>
          <ul>
            {ticket.detections.map((d, i) => (
              <li key={i}>
                {d.label} ({d.confidence.toFixed(2)}) [{d.box.join(", ")}]
              </li>
            ))}
          </ul>
          {ticket.output_url && (
            <img src={ticket.output_url} alt="output" style={{ maxWidth: "100%" }} />
          )}
          <div style={{ marginTop: 12 }}>
            <button onClick={reset}>Reset</button>
          </div>
        </div>
      )}

      {view === "error" && (
        <div>
          <p>Error: {error ?? ticket?.error}</p>
          <button onClick={reset}>Reset</button>
        </div>
      )}
    </div>
  );
}
