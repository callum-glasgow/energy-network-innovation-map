export type Lens = 'balanced' | 'profile' | 'source';
export type Measure = 'budget' | 'cost' | 'nia';
export type Money = {label:string; value:number|null; raw:string; field:string; checked_at:string|null};
export type ProjectNode = {
  id:string; title:string; reference:string; owner:string; status:string; participants:string[]; sector:string[]; funding:string[]; technology:string[]; themes:string[]; research:string[];
  start_date:string|null; end_date:string|null; invalid_dates:boolean; money:Record<Measure,Money>;
  preceding:{reference:string;field:string;state:string;id:string|null}[]; url:string; excerpt:string; checked_at:string|null;
  flags:string[]; semantic_hash:string; field_sources:Record<string,string>;
  coverage:{profile:boolean;passages:number;expected:number;complete:boolean};
};
export type Drawing = {positions:number[][]; groups:number[]; communities:{id:number;label:string;count:number;x:number;y:number}[]; edges:number[][]; isolated:number[];components:number;cutoff_counts:number[];fallbacks:('six'|'first'|null)[]};
export type Layout = Drawing & {variants:Record<string,Drawing>};
export type FocusRequest = {id:string;request:number};
export type ConnectionProximity = {minimum_neighbours:number|null;candidate_index?:number;rank?:number;reverse_rank?:number};
export type GraphData = {
  snapshot?:{format:number;root:string;scope:string;owners:string[];target_entries:number;row_bytes:number;license_url:string};
  revision:string; built_at:string; source_checked_at:string|null; nodes:ProjectNode[]; lenses:Record<Lens,Layout>;
  connection_proximity?:Record<Lens,ConnectionProximity[]>;
  lineage:{source:string;target:string;reference:string;field:string}[]; lineage_positions:number[][];cycles:string[][];
  financial_measures:{id:Measure;label:string;available:number}[];
  coverage:{catalogue:number;profile:number;source:number;passages:number;passages_expected:number};
  build_seconds:number; method:Record<string,string|number>;
};
export type Match = {id:string;balanced:number|null;profile:number|null;source:number|null};
export type Pair = {revision:string;a:string;b:string;scores:Omit<Match,'id'>;evidence:{a:{field:string;text:string;source_id:string};b:{field:string;text:string;source_id:string}}[];shared:Record<string,string[]>;different:Record<string,{a:string[];b:string[]}>};
