create table public.cities (
  city_code text primary key,
  name text not null,
  state text not null,
  ibge_code text not null,
  boundary_source_id text,
  h3_resolution int not null default 8,
  service_radius_m int not null default 1000,
  transit_radius_m int not null default 500,
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create table public.sources (
  source_id text primary key,
  city_code text not null references public.cities(city_code) on delete cascade,
  name text not null,
  publisher text not null,
  layer text,
  endpoint_url text not null,
  protocol text not null check (protocol in ('wfs','csv','geojson','overpass','api')),
  type_name text,
  category text,
  subcategory text,
  role text not null default 'service' check (role in ('service','context','demand')),
  geometry_hint text,
  approved boolean not null default false,
  verified_in_capabilities boolean,
  verified_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.discovered_layers (
  id uuid primary key default gen_random_uuid(),
  city_code text not null references public.cities(city_code) on delete cascade,
  endpoint_url text not null,
  layer_name text not null,
  title text,
  matched_terms text[] not null default '{}',
  feature_count bigint,
  count_error text,
  approved boolean not null default false,
  discovered_at timestamptz not null default now(),
  unique (city_code, layer_name)
);
create table public.runs (
  run_id uuid primary key default gen_random_uuid(),
  city_code text not null references public.cities(city_code) on delete cascade,
  step text not null,
  status text not null default 'running',
  cursor jsonb,
  summary jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);
create table public.run_logs (
  id bigserial primary key,
  run_id uuid references public.runs(run_id) on delete cascade,
  city_code text,
  source_id text,
  level text not null default 'info',
  message text not null,
  details jsonb,
  created_at timestamptz not null default now()
);

grant select on public.cities, public.sources, public.discovered_layers, public.runs, public.run_logs to anon, authenticated;
grant all on public.cities, public.sources, public.discovered_layers, public.runs, public.run_logs to service_role;
grant usage, select on sequence public.run_logs_id_seq to service_role;

alter table public.cities enable row level security;
alter table public.sources enable row level security;
alter table public.discovered_layers enable row level security;
alter table public.runs enable row level security;
alter table public.run_logs enable row level security;

create policy "public read" on public.cities for select to anon, authenticated using (true);
create policy "public read" on public.sources for select to anon, authenticated using (true);
create policy "public read" on public.discovered_layers for select to anon, authenticated using (true);
create policy "public read" on public.runs for select to anon, authenticated using (true);
create policy "public read" on public.run_logs for select to anon, authenticated using (true);

insert into public.cities (city_code, name, state, ibge_code, boundary_source_id)
values ('sp', 'São Paulo', 'SP', '3550308', 'sp_geosampa_area_contexto');

insert into public.sources (source_id, city_code, name, publisher, layer, endpoint_url, protocol, type_name, category, subcategory, role, geometry_hint) values
('sp_geosampa_educacao_rede_publica','sp','Public schools','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_educacao_rede_publica','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_educacao_rede_publica','school','primary_secondary','service','point'),
('sp_geosampa_educacao_infantil','sp','Public early-childhood education','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_educacao_infantil_rede_publica','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_educacao_infantil_rede_publica','school','early_childhood','service','point'),
('sp_geosampa_educacao_ceu','sp','CEU (Unified Educational Centres)','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_educacao_ceu','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_educacao_ceu','school','ceu','service','point'),
('sp_geosampa_saude_ubs','sp','Basic health units (UBS, posts, centres)','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_saude_ubs_posto_centro','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_saude_ubs_posto_centro','health_ubs',null,'service','point'),
('sp_geosampa_cras','sp','Social assistance reference centres (CRAS)','GeoSampa – SMUL/Geoinfo','geoportal:centro_referencia_assistencia_social','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:centro_referencia_assistencia_social','cras',null,'service','point'),
('sp_geosampa_parque_municipal','sp','Municipal parks','GeoSampa – SMUL/Geoinfo','geoportal:pde_parque_municipal','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:pde_parque_municipal','park_square','park','service','polygon'),
('sp_geosampa_praca_largo','sp','Squares and plazas','GeoSampa – SMUL/Geoinfo','geoportal:GEOSAMPA_v_praca_largo','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:GEOSAMPA_v_praca_largo','park_square','square','service','polygon'),
('sp_geosampa_bibliotecas','sp','Libraries','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_cultura_bibliotecas','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_cultura_bibliotecas','library',null,'service','point'),
('sp_geosampa_espacos_culturais','sp','Cultural spaces','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_cultura_espacos_culturais','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_cultura_espacos_culturais','culture','cultural_space','service','point'),
('sp_geosampa_museus','sp','Museums','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_cultura_museus','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_cultura_museus','culture','museum','service','point'),
('sp_geosampa_teatro_cinema_show','sp','Theatres, cinemas and venues','GeoSampa – SMUL/Geoinfo','geoportal:equipamento_cultura_teatro_cinema_show','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:equipamento_cultura_teatro_cinema_show','culture','theatre_cinema','service','point'),
('sp_geosampa_estacao_metro','sp','Metro stations','GeoSampa – SMUL/Geoinfo','geoportal:estacao_metro','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:estacao_metro','metro_train','metro','service','point'),
('sp_geosampa_distrito_municipal','sp','Municipal districts','GeoSampa – SMUL/Geoinfo','geoportal:distrito_municipal','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:distrito_municipal',null,null,'context','polygon'),
('sp_geosampa_area_contexto','sp','Municipal boundary','GeoSampa – SMUL/Geoinfo','geoportal:area_contexto','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:area_contexto',null,null,'context','polygon'),
('sp_geosampa_corredor_onibus','sp','Bus corridors (display only)','GeoSampa – SMUL/Geoinfo','geoportal:corredor_onibus','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:corredor_onibus',null,null,'context','line'),
('sp_geosampa_densidade_demografica','sp','Census tracts 2022 – population density','GeoSampa – SMUL/Geoinfo','geoportal:densidade_demografica','http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs','wfs','geoportal:densidade_demografica',null,null,'demand','polygon');