import { useEffect, useState } from "react";
import { api } from "../lib/api";

export type Job = {
  id: string;
  state: string;
  detail?: string;
  result_id?: string;
};

export const POLL_MS = 3000;
export const isActive = (job?: Job) =>
  ["queued", "running"].includes(job?.state ?? "");

/**
 * Tracks the submitted compute job, polling while it is queued or running.
 * Pass a stable callback (such as a state setter) as onError.
 */
export function useJobPolling(onError: (message: string) => void) {
  const [job, setJob] = useState<Job>();
  const jobId = job?.id;
  const active = isActive(job);

  useEffect(() => {
    if (!jobId || !active) return;
    let current = true;
    const poll = () => {
      void api<Job>(`jobs/${jobId}`)
        .then((next) => {
          if (current) setJob(next);
        })
        .catch((error: Error) => {
          if (current) onError(error.message);
        });
    };
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [jobId, active, onError]);

  return [job, setJob] as const;
}
