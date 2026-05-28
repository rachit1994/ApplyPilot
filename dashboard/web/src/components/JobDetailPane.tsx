import type { Job } from "../api";

type Props = {
  job: Job | null;
};

export function JobDetailPane({ job }: Props) {
  if (!job) {
    return (
      <aside className="job-detail" aria-label="Job details">
        <p className="panel__sub">Select a job to see fit score, resume path, and actions.</p>
      </aside>
    );
  }

  const score = job.fit_score;
  const scoreClass =
    score != null && score >= 8 ? "fact__value fact__value--acc" : "fact__value";

  return (
    <aside className="job-detail" aria-label="Job details">
      <div className="job-detail__hd">
        <div className="job-detail__statusrow">
          <span className="statusbar statusbar--new">Job</span>
        </div>
        <h2 className="job-detail__name">{job.title ?? "Untitled"}</h2>
        <p className="job-detail__company">
          {job.site ?? "—"}
          {job.url ? (
            <>
              {" · "}
              <a href={job.url} target="_blank" rel="noreferrer">
                View posting
              </a>
            </>
          ) : null}
        </p>
      </div>

      <div className="job-detail__facts">
        <div>
          <div className="fact__label">Fit score</div>
          <div className={scoreClass}>
            {score ?? "—"}
            {score != null ? <small>/10</small> : null}
          </div>
        </div>
        <div>
          <div className="fact__label">Location</div>
          <div className="fact__value">{job.location ?? "—"}</div>
        </div>
        <div>
          <div className="fact__label">Salary</div>
          <div className="fact__value">{job.salary ?? "—"}</div>
        </div>
        <div>
          <div className="fact__label">Apply status</div>
          <div className="fact__value">{job.apply_status ?? "—"}</div>
        </div>
      </div>

      {job.score_reasoning ? (
        <div className="job-detail__why">
          <p>{job.score_reasoning}</p>
        </div>
      ) : null}

      <div className="job-detail__actions">
        {job.url ? (
          <a className="btn btn--accent" href={job.url} target="_blank" rel="noreferrer">
            Open posting
          </a>
        ) : null}
        <button type="button" className="btn btn--ghost">
          Tailor resume
        </button>
      </div>
    </aside>
  );
}
