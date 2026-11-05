import { useState } from "react";
import { compileCode } from "./api.js";
import { EXAMPLES } from "./examples.js";

const TABS = ["Output", "Tokens", "AST", "IR vs Optimized", "LLVM IR"];

export default function App() {
  const [code, setCode] = useState(EXAMPLES["Hello, Chill"]);
  const [optimize, setOptimize] = useState(true);
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null); // network / server problems
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState("Output");

  async function run() {
    setLoading(true);
    setFailure(null);
    try {
      setResult(await compileCode(code, { optimize, run: true }));
    } catch (error) {
      setFailure(error.message);
    } finally {
      setLoading(false);
    }
  }

  // Ctrl/Cmd + Enter runs the program.
  function onKeyDown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") run();
  }

  return (
    <div className="app">
      <header className="toolbar">
        <h1>Chill <span>playground</span></h1>
        <select
          value=""
          onChange={(e) => e.target.value && setCode(EXAMPLES[e.target.value])}
        >
          <option value="">Examples…</option>
          {Object.keys(EXAMPLES).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <label>
          <input
            type="checkbox"
            checked={optimize}
            onChange={(e) => setOptimize(e.target.checked)}
          />
          Optimize
        </label>
        <button onClick={run} disabled={loading}>
          {loading ? "Running…" : "▶ Run (Ctrl+Enter)"}
        </button>
      </header>

      <main className="panes">
        <textarea
          className="editor"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={onKeyDown}
          spellCheck={false}
          aria-label="Chill source code"
        />

        <section className="results">
          <nav className="tabs">
            {TABS.map((name) => (
              <button
                key={name}
                className={name === tab ? "active" : ""}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </nav>
          <div className="tab-body">
            {failure && <p className="error-box">{failure}</p>}
            {!failure && !result && (
              <p className="hint">Press Run to compile your program.</p>
            )}
            {!failure && result && <Results result={result} tab={tab} />}
          </div>
        </section>
      </main>
    </div>
  );
}

function Results({ result, tab }) {
  if (!result.ok) return <ErrorList errors={result.errors} />;

  switch (tab) {
    case "Output":
      return (
        <>
          <pre className="output">{result.output || "(no output)"}</pre>
          {result.runError && <p className="error-box">{result.runError}</p>}
        </>
      );
    case "Tokens":
      return (
        <table className="tokens">
          <thead>
            <tr><th>Type</th><th>Text</th><th>Line:Col</th></tr>
          </thead>
          <tbody>
            {result.tokens.map((t, i) => (
              <tr key={i}>
                <td>{t.type}</td>
                <td>{t.text}</td>
                <td>{t.line}:{t.column}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    case "AST":
      return <pre>{result.ast}</pre>;
    case "IR vs Optimized":
      return (
        <>
          <p className="stats">
            Instructions: <b>{result.stats.before}</b> →{" "}
            <b>{result.stats.after}</b>
            {result.stats.before > result.stats.after &&
              ` (${result.stats.before - result.stats.after} removed)`}
          </p>
          <div className="diff">
            <div><h3>Before</h3><pre>{result.ir}</pre></div>
            <div><h3>After</h3><pre>{result.optimizedIr}</pre></div>
          </div>
        </>
      );
    case "LLVM IR":
      return <pre>{result.llvm}</pre>;
    default:
      return null;
  }
}

// Shows every compile error with its position and a pointer to the problem.
function ErrorList({ errors }) {
  return (
    <div>
      {errors.map((error, i) => (
        <pre key={i} className="error-box">{error.pretty}</pre>
      ))}
    </div>
  );
}
