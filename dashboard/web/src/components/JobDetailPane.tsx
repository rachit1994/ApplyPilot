import type { Job } from "../api";
import { jobTriageLabel } from "../utils/jobTriage";
import {
  displayJobField,
  formatApplyStatusDetail,
  formatFitScoreDetail,
  inferRemoteFromLocation,
} from "../utils/jobFacts";

type Props = {
  job: Job | null;
};

function formatPreFilterReason(reason: string | null | undefined): string {
  if (!reason) return "—";
  const labels: Record<string, string> = {
    "title:junior_or_intern": "Junior or intern title",
    "title:exec_non_eng": "Executive non-engineering role",
    "title:adjacent_role": "Adjacent non-core role",
    "title:not_in_allowlist": "Title outside target roles",
    "location:reject_pattern": "Location outside target regions",
    "salary:below_floor": "Salary below floor",
    "description:blocked_keyword": "Blocked JD keyword",
    "description:junior_signal": "Junior signal in JD",
    "profile:low_keyword_overlap": "Low profile/JD keyword overlap",
    "embedding_low": "Low resume/JD embedding match",
  };
  return labels[reason] ?? reason.replace(/_/g, " ");
}

export function JobDetailPane({ job }: Props) {
  if (!job) {
    return (
      <aside className="job-detail" aria-label="Job details">
        <p className="panel__sub">Select a job to see fit score, resume path, and actions.</p>
      </aside>
    );
  }

  const fit = formatFitScoreDetail(job);
  const scoreClass = fit.accent ? "fact__value fact__value--acc" : "fact__value";
  const remote = job.remote ?? inferRemoteFromLocation(job.location);

  return (
    <aside className="job-detail" aria-label="Job details">
      <div className="job-detail__hd">
        <div className="job-detail__statusrow">
          <span className="statusbar statusbar--new">{jobTriageLabel(job)}</span>
        </div>
        <h2 className="job-detail__name">{displayJobField(job.title)}</h2>
        <p className="job-detail__company">
          {displayJobField(job.site)}
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
          <div className={scoreClass}>{fit.text}</div>
        </div>
        <div>
          <div className="fact__label">Pre-score</div>
          <div className="fact__value">
            {job.pre_fit_score != null ? `${job.pre_fit_score}/10` : "—"}
          </div>
        </div>
        <div>
          <div className="fact__label">Location</div>
          <div className="fact__value">{displayJobField(job.location)}</div>
        </div>
        <div>
          <div className="fact__label">Remote</div>
          <div className="fact__value">{displayJobField(remote)}</div>
        </div>
        <div>
          <div className="fact__label">Salary</div>
          <div className="fact__value">{displayJobField(job.salary)}</div>
        </div>
        <div>
          <div className="fact__label">Apply status</div>
          <div className="fact__value">{formatApplyStatusDetail(job)}</div>
        </div>
      </div>

      {job.pre_filter_reason ? (
        <div className="job-detail__why job-detail__why--warn">
          <strong>Rejected before expensive review</strong>
          <p>{formatPreFilterReason(job.pre_filter_reason)}</p>
        </div>
      ) : null}

      {job.score_reasoning ? (
        <div className="job-detail__why">
          <p>{job.score_reasoning}</p>
        </div>
      ) : null}

      {job.detail_error ? (
        <div className="job-detail__why">
          <p className="text-warn">Enrich: {job.detail_error}</p>
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
