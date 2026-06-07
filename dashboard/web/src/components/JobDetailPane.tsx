import type { Job } from "../api";
import { jobTriageLabel } from "../utils/jobTriage";
import { statusbarClass } from "../utils/statusbar";
import {
  companyInitials,
  companyLabelFromSite,
  displayJobField,
  formatApplyStatusDetail,
  formatFitScoreDetail,
  formatPreFilterReason,
  inferRemoteFromLocation,
} from "../utils/jobFacts";

type Props = {
  job: Job | null;
  onSkip?: () => void;
};

export function JobDetailPane({ job, onSkip }: Props) {
  if (!job) {
    return (
      <aside className="job-detail" aria-label="Job details">
        <p className="panel__sub">Select a job to review fit, reasoning, and apply actions.</p>
      </aside>
    );
  }

  const fit = formatFitScoreDetail(job);
  const scoreClass = fit.accent ? "fact__value fact__value--acc" : "fact__value";
  const remote = job.remote ?? inferRemoteFromLocation(job.location);
  const company = companyLabelFromSite(job.site);
  const initials = companyInitials(company === "—" ? (job.title ?? "?") : company);
  const saved = Boolean(job.tailored_at || job.tailored_resume_path);
  const applyHref = job.application_url || job.url;

  return (
    <aside className="job-detail" aria-label="Job details">
      <div className="job-detail__hd">
        <div className="job-detail__brand">
          <span className="job-detail__logo" aria-hidden>
            {initials}
          </span>
          <div className="job-detail__brand-copy">
            <div className="job-detail__statusrow">
              <span className={statusbarClass(jobTriageLabel(job))}>{jobTriageLabel(job)}</span>
            </div>
            <h2 className="job-detail__name">{displayJobField(job.title)}</h2>
            <p className="job-detail__company">
              {company}
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
        </div>
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
          <div className="job-detail__why-label">Why ApplyPilot picked this</div>
          <p>{job.score_reasoning}</p>
        </div>
      ) : null}

      {job.detail_error ? (
        <div className="job-detail__why">
          <p className="text-warn">Enrich: {job.detail_error}</p>
        </div>
      ) : null}

      <div className="job-detail__actions">
        <button type="button" className="btn btn--ghost" onClick={onSkip} disabled={!onSkip}>
          Skip
        </button>
        <button type="button" className="btn btn--ghost" disabled={saved} title={saved ? "Resume already tailored" : undefined}>
          {saved ? "Saved" : "Save"}
        </button>
        {applyHref ? (
          <a className="btn btn--accent" href={applyHref} target="_blank" rel="noreferrer">
            Apply
          </a>
        ) : (
          <button type="button" className="btn btn--accent" disabled>
            Apply
          </button>
        )}
      </div>
    </aside>
  );
}