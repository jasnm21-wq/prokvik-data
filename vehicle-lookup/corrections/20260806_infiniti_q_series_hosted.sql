-- Hosted correction applied and verified on 2026-08-06.
-- Scope: Infiniti Q45, Q50, Q60, Q70, and Q70L only.
-- QX models are intentionally excluded.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '30s';

do $$
declare
  missing_models text[];
begin
  select array_agg(target_model order by target_model)
  into missing_models
  from (
    values ('Q45'), ('Q50'), ('Q60'), ('Q70'), ('Q70L')
  ) as targets(target_model)
  where not exists (
    select 1
    from public.vehicle_lookup row_before
    where regexp_replace(upper(trim(row_before.make)), '[^A-Z0-9]', '', 'g') = 'INFINITI'
      and regexp_replace(upper(trim(row_before.model)), '[^A-Z0-9]', '', 'g') = targets.target_model
  );

  if missing_models is not null then
    raise exception
      'Infiniti correction stopped: missing models: %',
      array_to_string(missing_models, ', ');
  end if;
end
$$;

update public.vehicle_lookup
set
  vehicle_class = case
    when regexp_replace(upper(trim(model)), '[^A-Z0-9]', '', 'g') = 'Q60'
      then 'coupe'
    else 'sedan'
  end,
  pricing_group = case
    when regexp_replace(upper(trim(model)), '[^A-Z0-9]', '', 'g') = 'Q60'
      then 'Coupe'
    else 'Sedan'
  end,
  classification_source = 'manual_correction_infiniti_q_series',
  review_status = 'ok',
  is_commercial = false
where regexp_replace(upper(trim(make)), '[^A-Z0-9]', '', 'g') = 'INFINITI'
  and regexp_replace(upper(trim(model)), '[^A-Z0-9]', '', 'g')
    in ('Q45', 'Q50', 'Q60', 'Q70', 'Q70L');

do $$
begin
  if exists (
    select 1
    from public.vehicle_lookup row_after
    where regexp_replace(upper(trim(row_after.make)), '[^A-Z0-9]', '', 'g') = 'INFINITI'
      and regexp_replace(upper(trim(row_after.model)), '[^A-Z0-9]', '', 'g')
        in ('Q45', 'Q50', 'Q60', 'Q70', 'Q70L')
      and (
        row_after.vehicle_class is distinct from case
          when regexp_replace(upper(trim(row_after.model)), '[^A-Z0-9]', '', 'g') = 'Q60'
            then 'coupe'
          else 'sedan'
        end
        or row_after.pricing_group is distinct from case
          when regexp_replace(upper(trim(row_after.model)), '[^A-Z0-9]', '', 'g') = 'Q60'
            then 'Coupe'
          else 'Sedan'
        end
      )
  ) then
    raise exception 'Infiniti Q-series correction contract failed';
  end if;

  if exists (
    select 1
    from public.vehicle_lookup
    where regexp_replace(upper(trim(make)), '[^A-Z0-9]', '', 'g') = 'INFINITI'
      and regexp_replace(upper(trim(model)), '[^A-Z0-9]', '', 'g') like 'QX%'
      and (vehicle_class <> 'suv' or pricing_group <> 'SUV')
  ) then
    raise exception 'Infiniti QX SUV contract failed';
  end if;
end
$$;

commit;
