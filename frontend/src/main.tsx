import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  ChevronDown,
  CircleHelp,
  Globe2,
  Layers2,
  LoaderCircle,
  Play,
  Plus,
  RotateCcw,
  Search,
  Settings2,
  X,
} from "lucide-react";
import { api, ApiError } from "./api";
import { demo, blank } from "./config";
import type { Config, Field, Result } from "./types";
import { ResultsPanel } from "./ResultsPanel";
import "./style.css";

function App() {
  const [config, setConfig] = useState<Config>(blank),
    [result, setResult] = useState<Result | null>(null),
    [names, setNames] = useState<string[]>([]),
    [job, setJob] = useState<string | null>(null),
    [busy, setBusy] = useState<"preview" | "start" | null>(null),
    [error, setError] = useState(""),
    [help, setHelp] = useState(false),
    [stopping, setStopping] = useState(false),
    [advanced, setAdvanced] = useState(false),
    [source, setSource] = useState(false),
    [customAttributes, setCustomAttributes] = useState<Set<number>>(new Set());
  const helpTrigger = useRef<HTMLElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);
  const [viewRevision, setViewRevision] = useState(0);
  const openHelp = (event: React.MouseEvent<HTMLButtonElement>) => {
    helpTrigger.current = event.currentTarget;
    setHelp(true);
  };
  const running = !!job && (!result || result.status === "running");
  const locked = running || !!busy;
  const update = <K extends keyof Config>(key: K, value: Config[K]) =>
    setConfig((c) => ({ ...c, [key]: value }));
  const field = (i: number, key: keyof Field, value: string) =>
    setConfig((c) => ({
      ...c,
      fields: c.fields.map((f, j) => (i === j ? { ...f, [key]: value } : f)),
    }));
  const chooseAttribute = (index: number, value: string) => {
    setCustomAttributes((previous) => {
      const next = new Set(previous);
      if (value === "custom") next.add(index);
      else next.delete(index);
      return next;
    });
    field(index, "attribute", value === "custom" ? "" : value);
  };
  const removeField = (index: number) => {
    update(
      "fields",
      config.fields.filter((_, i) => i !== index),
    );
    setCustomAttributes(
      (previous) =>
        new Set(
          [...previous]
            .filter((i) => i !== index)
            .map((i) => (i > index ? i - 1 : i)),
        ),
    );
  };
  useEffect(() => {
    if (!job) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const poll = async () => {
      try {
        const r = await api<Result>("/jobs/" + job);
        if (disposed) return;
        setResult(r);
        if (r.fields) setNames(r.fields);
        if (failures) setError("");
        failures = 0;
        if (r.status === "running") timer = setTimeout(poll, 650);
        else setStopping(false);
      } catch (e) {
        if (disposed) return;
        if (e instanceof ApiError && e.status === 404) {
          setJob(null);
          setResult(null);
          setError(e.message);
          return;
        }
        setError((e as Error).message + " Retrying…");
        failures++;
        timer = setTimeout(poll, Math.min(5000, 1000 * failures));
      }
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [job]);
  const loadDemo = () => {
    setConfig(structuredClone(demo));
    setCustomAttributes(new Set());
    setError("");
  };
  async function preview() {
    if (!formRef.current?.reportValidity()) return;
    setBusy("preview");
    setError("");
    try {
      const r = await api<Result>("/preview", config);
      setJob(null);
      setNames(r.fields ?? config.fields.map((f) => f.name.trim()));
      setResult(r);
      setViewRevision((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function start() {
    if (!formRef.current?.reportValidity()) return;
    setBusy("start");
    setError("");
    try {
      const r = await api<{ id: string }>("/jobs", config);
      setResult(null);
      setNames(config.fields.map((f) => f.name.trim()));
      setJob(r.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function stop() {
    setStopping(true);
    try {
      await api("/jobs/" + job + "/cancel", {});
    } catch (e) {
      setError((e as Error).message);
      setStopping(false);
    }
  }
  useEffect(() => {
    if (!help) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setHelp(false);
        return;
      }
      if (e.key === "Tab") {
        const nodes = Array.from(
          document.querySelectorAll<HTMLElement>(
            ".help-modal button, .help-modal a, .help-modal input",
          ),
        );
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
        if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = previousOverflow;
      helpTrigger.current?.focus();
    };
  }, [help]);
  const valid =
    !!config.url &&
    !!config.row_selector &&
    config.fields.every((f) => f.name.trim());
  return (
    <>
      <header className="topbar" inert={help}>
        <div className="brand">
          <span className="brand-icon">
            <Layers2 size={19} />
          </span>
          <span>Website Data Extractor</span>
        </div>
        <button tabIndex={0} className="quiet" onClick={openHelp}>
          <CircleHelp size={16} /> Quick guide
        </button>
      </header>
      <main inert={help}>
        <div className="page-heading">
          <div>
            <h1>New extraction</h1>
            <p>Extract structured records with CSS selectors.</p>
          </div>
        </div>
        <div className="workspace">
          <section
            className="configuration"
            aria-label="Extraction configuration"
          >
            <div className="panel-title">
              <span>
                <Settings2 size={17} /> Configure extraction
              </span>
              <button
                tabIndex={0}
                className="icon-button"
                aria-label="Reset configuration"
                title="Reset configuration"
                disabled={locked}
                onClick={() => {
                  setConfig(structuredClone(blank));
                  setCustomAttributes(new Set());
                  setError("");
                }}
              >
                <RotateCcw size={15} />
              </button>
            </div>
            <form
              ref={formRef}
              onSubmit={(e) => {
                e.preventDefault();
                void preview();
              }}
            >
              <div
                className="config-scroll"
                role="region"
                aria-label="Configuration settings"
                tabIndex={0}
              >
                <fieldset disabled={locked}>
                  <section className="config-section">
                    <div className="section-label">
                      <span className="step">1</span>
                      <h2>Source</h2>
                    </div>
                    <label htmlFor="url">Website URL</label>
                    <div className="input-icon">
                      <Globe2 size={15} />
                      <input
                        id="url"
                        type="url"
                        placeholder="https://example.com/catalog"
                        value={config.url}
                        onChange={(e) => update("url", e.target.value)}
                        required
                      />
                    </div>
                    <div className="demo-line">
                      <span>Need a starting point?</span>
                      <button tabIndex={0} type="button" onClick={loadDemo}>
                        Load bookshop demo <ArrowRight size={12} />
                      </button>
                    </div>
                    <label className="check-row js-toggle">
                      <input
                        tabIndex={0}
                        type="checkbox"
                        checked={config.render_js}
                        onChange={(e) => update("render_js", e.target.checked)}
                      />
                      <span>Render JavaScript</span>
                      <span className="tag">Playwright</span>
                    </label>
                  </section>
                  <section className="config-section">
                    <div className="section-label">
                      <span className="step">2</span>
                      <h2>Records & fields</h2>
                      <button
                        tabIndex={0}
                        type="button"
                        className="icon-button"
                        aria-label="Selector help"
                        onClick={openHelp}
                      >
                        <CircleHelp size={14} />
                      </button>
                    </div>
                    <label htmlFor="row">Record selector</label>
                    <input
                      id="row"
                      className="mono"
                      placeholder=".product-card"
                      value={config.row_selector}
                      onChange={(e) => update("row_selector", e.target.value)}
                      required
                    />
                    <p className="hint">One matching element = one row.</p>
                    <div className="fields-label">
                      <span>FIELD NAME</span>
                      <span>CSS SELECTOR</span>
                    </div>
                    <div className="fields">
                      {config.fields.map((f, i) => (
                        <div className="field" key={i}>
                          <div className="field-inputs">
                            <input
                              aria-label={`Field ${i + 1} name`}
                              value={f.name}
                              placeholder="Name"
                              required
                              onChange={(e) => field(i, "name", e.target.value)}
                            />
                            <input
                              className="mono"
                              aria-label={`Field ${i + 1} selector`}
                              value={f.selector}
                              placeholder=".title (blank: record)"
                              onChange={(e) =>
                                field(i, "selector", e.target.value)
                              }
                            />
                            <button
                              tabIndex={0}
                              className="icon-button delete"
                              aria-label={`Remove field ${i + 1}`}
                              disabled={config.fields.length === 1}
                              type="button"
                              onClick={() => removeField(i)}
                            >
                              <X size={14} />
                            </button>
                          </div>
                          <div className="attribute">
                            <label htmlFor={"attr" + i}>Value</label>
                            <select
                              id={"attr" + i}
                              value={
                                customAttributes.has(i) ? "custom" : f.attribute
                              }
                              onChange={(e) =>
                                chooseAttribute(i, e.target.value)
                              }
                            >
                              <option value="">Text content</option>
                              <option value="href">Link · href</option>
                              <option value="src">Image · src</option>
                              <option value="title">Title attribute</option>
                              <option value="data-id">Data ID</option>
                              <option value="custom">Custom attribute</option>
                            </select>
                            {customAttributes.has(i) && (
                              <input
                                aria-label={`Field ${i + 1} custom attribute`}
                                required
                                placeholder="data-sku"
                                value={f.attribute}
                                onChange={(e) =>
                                  field(i, "attribute", e.target.value)
                                }
                              />
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                    <button
                      tabIndex={0}
                      type="button"
                      className="add-field"
                      disabled={config.fields.length >= 20}
                      onClick={() =>
                        update("fields", [
                          ...config.fields,
                          {
                            name: "Field " + (config.fields.length + 1),
                            selector: "",
                            attribute: "",
                          },
                        ])
                      }
                    >
                      <Plus size={14} /> Add field
                    </button>
                  </section>
                  <section className="config-section pagination-section">
                    <div className="section-label">
                      <span className="step">3</span>
                      <h2>Pagination</h2>
                      <span className="optional">Optional</span>
                    </div>
                    <label htmlFor="next">Next page selector</label>
                    <input
                      id="next"
                      className="mono"
                      placeholder="a.next"
                      value={config.next_selector}
                      onChange={(e) => update("next_selector", e.target.value)}
                    />
                    <div className="two-col">
                      <div>
                        <label htmlFor="limit">Page limit</label>
                        <div className="input-unit">
                          <input
                            id="limit"
                            type="number"
                            min="1"
                            max="50"
                            required
                            value={config.max_pages}
                            onChange={(e) =>
                              update("max_pages", Number(e.target.value))
                            }
                          />
                          <span>pages</span>
                        </div>
                      </div>
                      <div>
                        <label htmlFor="delay">Request delay</label>
                        <div className="input-unit">
                          <input
                            id="delay"
                            type="number"
                            min="0.5"
                            max="30"
                            step="0.5"
                            required
                            value={config.delay}
                            onChange={(e) =>
                              update("delay", Number(e.target.value))
                            }
                          />
                          <span>sec</span>
                        </div>
                      </div>
                    </div>
                  </section>
                  <div className="advanced">
                    <button
                      tabIndex={0}
                      type="button"
                      aria-expanded={advanced}
                      onClick={() => setAdvanced(!advanced)}
                    >
                      <Settings2 size={14} /> Advanced settings{" "}
                      <ChevronDown
                        size={14}
                        className={advanced ? "rotated" : ""}
                      />
                    </button>
                    {advanced && (
                      <div className="advanced-body">
                        <label className="check-row">
                          <input
                            tabIndex={0}
                            type="checkbox"
                            checked={config.deduplicate}
                            onChange={(e) =>
                              update("deduplicate", e.target.checked)
                            }
                          />{" "}
                          Remove duplicate records
                        </label>
                        <label className="check-row">
                          <input
                            tabIndex={0}
                            type="checkbox"
                            checked={source}
                            onChange={(e) => setSource(e.target.checked)}
                          />{" "}
                          Show source URL in table
                        </label>
                        <label htmlFor="timeout">Page timeout (seconds)</label>
                        <input
                          id="timeout"
                          type="number"
                          min="2"
                          max="30"
                          value={config.timeout}
                          onChange={(e) =>
                            update("timeout", Number(e.target.value))
                          }
                        />
                        <p className="hint">
                          Up to 5,000 records per run. Source URLs are always
                          exported.
                        </p>
                      </div>
                    )}
                  </div>
                </fieldset>
              </div>
              <div className="config-actions">
                <button
                  tabIndex={0}
                  type="submit"
                  className="button secondary"
                  disabled={locked || !valid}
                >
                  {busy === "preview" ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Search size={15} />
                  )}{" "}
                  Preview
                </button>
                <button
                  tabIndex={0}
                  type="button"
                  className="button primary"
                  onClick={() => void start()}
                  disabled={locked || !valid}
                >
                  {busy === "start" ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Play size={14} />
                  )}{" "}
                  Start extraction
                </button>
              </div>
            </form>
          </section>
          <ResultsPanel
            result={result}
            viewRevision={viewRevision}
            names={names}
            job={job}
            busy={busy}
            error={error}
            setError={setError}
            running={running}
            stopping={stopping}
            stop={stop}
            source={source}
            maxPages={config.max_pages}
            loadDemo={loadDemo}
          />
        </div>
      </main>
      {help && (
        <div className="modal-backdrop" onClick={() => setHelp(false)}>
          <section
            className="help-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="help-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              tabIndex={0}
              className="icon-button modal-close"
              aria-label="Close guide"
              autoFocus
              onClick={() => setHelp(false)}
            >
              <X size={18} />
            </button>
            <h2 id="help-title">A quick guide</h2>
            <p>Use your browser’s Inspect tool to find CSS selectors.</p>
            <ol>
              <li>
                <strong>Choose a record.</strong> A repeating container like{" "}
                <code>.book</code> becomes one row.
              </li>
              <li>
                <strong>Choose fields inside it.</strong> Use <code>h2</code>{" "}
                for a title or <code>a</code> with the <code>href</code>{" "}
                attribute for a link. An empty selector uses the record itself.
              </li>
              <li>
                <strong>Set pagination.</strong> Choose the next-page link, such
                as <code>a.next</code>. Only links on the same origin are
                followed.
              </li>
              <li>
                <strong>Preview, then extract.</strong> Check your columns and
                missing values. Start extraction to enable CSV and Excel
                exports.
              </li>
            </ol>
            <p>
              JavaScript mode needs Playwright’s Chromium browser. It supports
              same-origin scripts and GET requests; third-party resources,
              logins, and interactive pagination are excluded.
            </p>
            <div className="help-note">
              <span>
                Use pages you’re permitted to access. Robots.txt is enforced;
                this tool does not bypass site restrictions.
              </span>
            </div>
            <button
              tabIndex={0}
              className="button primary"
              onClick={() => setHelp(false)}
            >
              Got it
            </button>
          </section>
        </div>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
