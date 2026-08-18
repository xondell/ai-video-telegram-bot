alter table public.jobs drop constraint if exists ck_jobs_cost_hard_cap;

alter table public.jobs add constraint ck_jobs_cost_hard_cap
  check (
    estimated_cost >= 0
    and reserved_cost >= 0
    and actual_cost >= 0
    and actual_cost + reserved_cost <= 5.00
  );
