// Hash routing (#/pipeline/B-123, #/review/DOC, #/doc/DOC, ...) so the static build works on any host.
import { useEffect, useState } from "react";
import Header from "./components/Header.jsx";
import { Toast } from "./components/ui.jsx";
import DocDetail from "./pages/DocDetail.jsx";
import LlmLog from "./pages/LlmLog.jsx";
import Metrics from "./pages/Metrics.jsx";
import Overview from "./pages/Overview.jsx";
import Pipeline from "./pages/Pipeline.jsx";
import Review from "./pages/Review.jsx";

function parseHash() {
  const [page = "", id] = window.location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  return { page: page || "overview", id };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [error, setError] = useState(null);
  useEffect(() => {
    const onHash = () => { setRoute(parseHash()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => { if (!error) return; const t = setTimeout(() => setError(null), 6000); return () => clearTimeout(t); }, [error]);

  const { page, id } = route;
  const active = page === "doc" ? "pipeline" : page;
  return (
    <div className="page">
      <Header active={active} onError={setError} />
      {page === "overview" && <Overview onError={setError} />}
      {page === "pipeline" && <Pipeline key={id || "latest"} batchId={id} onError={setError} />}
      {page === "review" && <Review docId={id} onError={setError} />}
      {page === "doc" && id && <DocDetail docId={id} onError={setError} />}
      {page === "metrics" && <Metrics onError={setError} />}
      {page === "llm-log" && <LlmLog onError={setError} />}
      <Toast message={error} onClose={() => setError(null)} />
    </div>
  );
}
