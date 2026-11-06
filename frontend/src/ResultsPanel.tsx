import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  Globe2,
  LoaderCircle,
  Search,
  Square,
  Table2,
  Terminal,
  TriangleAlert,
  X,
} from "lucide-react";
import type { Result } from "./types";
type Props = {
  result: Result | null;
  viewRevision: number;
  names: string[];
  job: string | null;
  busy: string | null;
  error: string;
  setError: (v: string) => void;
  running: boolean;
  stopping: boolean;
  stop: () => Promise<void>;
  source: boolean;
  maxPages: number;
  loadDemo: () => void;
};
export function ResultsPanel({
  result,
  viewRevision,
  names,
  job,
  busy,
  error,
  setError,
  running,
  stopping,
  stop,
  source,
  maxPages,
  loadDemo,
}: Props) {
  const [tab, setTab] = useState<"data" | "activity">("data"),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0);
  useEffect(() => {
    setTab("data");
    setQuery("");
    setPage(0);
  }, [job, viewRevision]);
  const rows = (result?.records || []).filter((row) =>
    Object.values(row).some((v) =>
      v.toLowerCase().includes(query.toLowerCase()),
    ),
  );
  const pages = Math.max(1, Math.ceil(rows.length / 10));
  const currentPage = Math.min(page, pages - 1);
  const previewed = !!result && !job;
  return (
    <section className="results-panel" aria-label="Extraction results">
      <div className="results-heading">
        <div>
          <h2>
            Results <span className="badge">{result?.records.length || 0}</span>
          </h2>
          <p>
            {running
              ? "Collecting records. Results appear as pages finish."
              : previewed
                ? result?.status === "failed"
                  ? "Preview failed. Check Activity for details."
                  : "Preview · first page, up to 10 records"
                : job
                  ? result?.records.length
                    ? "Collected records are ready to export."
                    : "No records collected. Check Activity for details."
                  : "Preview your fields before running an extraction."}
          </p>
        </div>
        {running ? (
          <button
            tabIndex={0}
            className="button secondary small"
            disabled={stopping}
            onClick={() => void stop()}
          >
            <Square size={12} />
            {stopping ? "Stopping…" : "Stop run"}
          </button>
        ) : (
          <span className={"status " + (result ? result.status : "")}>
            <span />
            {busy === "preview"
              ? "Previewing"
              : result?.status === "completed" && !result.records.length
                ? "No matches"
                : result
                  ? {
                      completed: "Ready",
                      partial: "Partial results",
                      failed: "Failed",
                      cancelled: "Stopped",
                    }[result.status] || "Ready"
                  : "Not started"}
          </span>
        )}
      </div>
      {error && (
        <div className="alert" role="alert">
          <TriangleAlert size={16} />
          <span>{error}</span>
          <button
            tabIndex={0}
            className="icon-button"
            aria-label="Dismiss error"
            onClick={() => setError("")}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {busy === "preview" && (
        <div className="preview-loading" role="status">
          <LoaderCircle size={14} className="spin" /> Preparing preview…
        </div>
      )}
      {running && (
        <div className="progress" role="status">
          <div>
            <LoaderCircle size={15} className="spin" />
            <span>
              {stopping
                ? "Stopping after the current page…"
                : `Extracting page ${result?.attempted || 1} of ${maxPages}`}
            </span>
            <span>{result?.records.length || 0} records collected</span>
          </div>
          <div className="progress-track">
            <span
              style={{
                width: `${Math.max(4, ((result?.pages || 0) / maxPages) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}
      <div className="result-toolbar">
        <div className="tabs">
          <button
            tabIndex={0}
            className={tab === "data" ? "selected" : ""}
            onClick={() => setTab("data")}
          >
            <Table2 size={15} /> Data
          </button>
          <button
            tabIndex={0}
            className={tab === "activity" ? "selected" : ""}
            onClick={() => setTab("activity")}
          >
            <Terminal size={15} /> Activity
            {!!result?.issues.length && (
              <span className="issue-count">{result.issues.length}</span>
            )}
          </button>
        </div>
        <div className="exports">
          <a
            className={
              "export-button " +
              (!job || !result?.records.length ? "disabled" : "")
            }
            href={
              job && result?.records.length
                ? `/api/jobs/${job}/export/csv`
                : undefined
            }
            tabIndex={!job || !result?.records.length ? -1 : 0}
            aria-disabled={!job || !result?.records.length}
          >
            <ArrowDownToLine size={14} /> CSV
          </a>
          <a
            className={
              "export-button " +
              (!job || !result?.records.length ? "disabled" : "")
            }
            href={
              job && result?.records.length
                ? `/api/jobs/${job}/export/xlsx`
                : undefined
            }
            tabIndex={!job || !result?.records.length ? -1 : 0}
            aria-disabled={!job || !result?.records.length}
          >
            <FileSpreadsheet size={14} /> Excel
          </a>
        </div>
      </div>
      {tab === "data" ? (
        <>
          {!!result?.records.length && (
            <div className="table-search">
              <div className="input-icon">
                <Search size={14} />
                <input
                  aria-label="Search results"
                  placeholder="Search records…"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                />
              </div>
              <span>
                {names.length} fields{source ? " + source" : ""}
              </span>
            </div>
          )}
          {result?.records.length ? (
            <>
              <div
                className="table-wrap"
                tabIndex={0}
                role="region"
                aria-label="Extracted records"
              >
                <table>
                  <thead>
                    <tr>
                      <th className="row-num">#</th>
                      {[...names, ...(source ? ["_source"] : [])].map((n) => (
                        <th key={n}>{n === "_source" ? "Source URL" : n}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows
                      .slice(currentPage * 10, currentPage * 10 + 10)
                      .map((row, i) => (
                        <tr key={i}>
                          <td className="row-num">
                            {currentPage * 10 + i + 1}
                          </td>
                          {[...names, ...(source ? ["_source"] : [])].map(
                            (n) => (
                              <td key={n} title={row[n] || "Missing value"}>
                                {row[n] || (
                                  <span className="missing">Missing</span>
                                )}
                              </td>
                            ),
                          )}
                        </tr>
                      ))}
                  </tbody>
                </table>
                {!rows.length && (
                  <p className="no-matches">No records match “{query}”.</p>
                )}
              </div>
              <div className="table-footer">
                <span>
                  {rows.length ? currentPage * 10 + 1 : 0}–
                  {Math.min((currentPage + 1) * 10, rows.length)} of{" "}
                  {rows.length} records
                </span>
                <div>
                  <button
                    tabIndex={0}
                    className="icon-button"
                    aria-label="Previous results page"
                    disabled={!currentPage}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span>
                    {currentPage + 1} / {pages}
                  </span>
                  <button
                    tabIndex={0}
                    className="icon-button"
                    aria-label="Next results page"
                    disabled={currentPage >= pages - 1}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-art">
                <div className="mini-browser">
                  <span />
                  <span />
                  <span />
                  <div>
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
                <ArrowRight size={20} />
                <div className="mini-table">
                  <Table2 size={40} strokeWidth={1} />
                </div>
              </div>
              <h3>
                {busy === "preview"
                  ? "Checking your selectors…"
                  : running
                    ? "Your extraction is running…"
                    : result
                      ? "No records found"
                      : "Preview your data"}
              </h3>
              <p>
                {result && !running
                  ? "Check your selectors and the Activity tab for details."
                  : "Load the demo or enter a URL, then preview your fields."}
              </p>
              {!result && !running && !busy && (
                <button
                  tabIndex={0}
                  className="button secondary"
                  onClick={loadDemo}
                >
                  Try the bookshop demo <ArrowRight size={14} />
                </button>
              )}
              {(busy || running) && <LoaderCircle size={20} className="spin" />}
            </div>
          )}
        </>
      ) : (
        <div className="activity">
          <div className="activity-title">RUN LOG</div>
          {!result ? (
            <p>Page activity and errors will appear here.</p>
          ) : (
            <>
              <div className="log-entry">
                <Check size={15} />
                <div>
                  <strong>
                    {result.pages} of {result.attempted} pages extracted
                  </strong>
                  <p>{result.stop_reason || "Extraction in progress…"}</p>
                </div>
              </div>
              {result.issues.map((issue, i) => (
                <div className="log-entry warning" key={i}>
                  <TriangleAlert size={15} />
                  <div>
                    <strong>{issue.message}</strong>
                    <p>{issue.page}</p>
                  </div>
                </div>
              ))}
              {result.current_url && (
                <div className="log-entry">
                  <Globe2 size={15} />
                  <div>
                    <strong>Last page</strong>
                    <p>{result.current_url}</p>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
      {result && (
        <div className="result-summary" aria-live="polite">
          <span>
            <Check size={14} />
            {result.pages} {result.pages === 1 ? "page" : "pages"}
          </span>
          <span>{result.duplicates} duplicates removed</span>
          <span className={result.missing ? "warning-text" : ""}>
            {!!result.missing && <TriangleAlert size={13} />} {result.missing}{" "}
            missing values
          </span>
          {previewed && !!result.records.length && (
            <span className="preview-note">
              Run extraction to export <ArrowRight size={12} />
            </span>
          )}
        </div>
      )}
      {result?.stop_reason && !running && (
        <div className="results-bottom" role="status">
          <span>{result.stop_reason}</span>
        </div>
      )}
    </section>
  );
}
