import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Field, Input, Select, Spinner, Tab, TabList } from '@fluentui/react-components';
import { ArrowClockwiseRegular, ArrowLeftRegular, ChartMultipleRegular, DataTrendingRegular, DocumentRegular, LibraryRegular, SearchRegular } from '@fluentui/react-icons';
import { libraryApi, formatDate, formatNumber } from './library';
import { DocumentActions, Empty, LibraryChart, LibraryError, Pager, Stat, Status, statusLabels, useRemote } from './LibraryShared';
import { useLibraryStyles } from './libraryStyles';
import { formatBytes } from './storage';
import LibraryIndexing from './LibraryIndexing';
import LibraryPerformance from './LibraryPerformance';
import LibraryDocumentDetail from './LibraryDocumentDetail';
import type { LibrarySort, LibraryStatus } from './libraryTypes';
import type { ChartSpec } from './LibraryChart';

type Section = 'collection' | 'indexing' | 'performance';
export default function LibraryPage({ onBack, onDocumentsChanged }: { onBack: () => void; onDocumentsChanged: () => void }) {
  const styles = useLibraryStyles();
  const [section, setSection] = useState<Section>('collection');
  const [version, setVersion] = useState(0);
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const lastDocument = useRef<string | null>(null);
  const summaryLoader = useCallback((signal: AbortSignal) => libraryApi.summary(signal), []);
  const summary = useRemote(summaryLoader, version);
  useEffect(() => { heading.current?.focus(); }, []);
  const refresh = () => setVersion((value) => value + 1);
  const changed = () => { refresh(); onDocumentsChanged(); };
  const closeDetail = () => {
    setSelected(null);
    requestAnimationFrame(() => {
      const button = lastDocument.current ? document.getElementById(`library-document-${lastDocument.current}`) : null;
      (button ?? heading.current)?.focus();
    });
  };
  return <div className={styles.page}>
    <header className={styles.header}><div className={styles.titleRow}><Button icon={<ArrowLeftRegular />} appearance="subtle" onClick={selected ? closeDetail : onBack}>{selected ? 'Voltar' : 'Conversa'}</Button><span className={styles.titleIcon}><LibraryRegular aria-hidden /></span><h1 className={styles.heading} ref={heading} tabIndex={-1}>Biblioteca</h1></div><Button icon={summary.loading ? <Spinner size="tiny" /> : <ArrowClockwiseRegular />} appearance="subtle" onClick={refresh}>Atualizar</Button></header>
    {!selected && <div className={styles.tabs}><TabList aria-label="Contexto da biblioteca" selectedValue={section} onTabSelect={(_, value) => setSection(value.value as Section)}><Tab id="library-tab-collection" value="collection" icon={{ children: <LibraryRegular />, className: styles.tabIcon }}>Acervo</Tab><Tab id="library-tab-indexing" value="indexing" icon={{ children: <ChartMultipleRegular />, className: styles.tabIcon }}>Indexação</Tab><Tab id="library-tab-performance" value="performance" icon={{ children: <DataTrendingRegular />, className: styles.tabIcon }}>Desempenho</Tab></TabList></div>}
    <main className={styles.scroll} aria-label={selected ? `Detalhes de ${selected.name}` : 'Gerenciamento da biblioteca'}><div className={styles.content}>
      {selected && <LibraryDocumentDetail id={selected.id} name={selected.name} version={version} onChange={changed} onRemoved={closeDetail} />}<div role="tabpanel" id={`library-panel-${section}`} aria-labelledby={`library-tab-${section}`} className={styles.content} style={selected ? { display: 'none' } : undefined} aria-busy={summary.loading}>
        <LibraryError message={summary.error} />
        {section === 'collection' && <>
          {summary.data ? <><div className={styles.kpis}><Stat label="Documentos" value={formatNumber(summary.data.documents.total)} /><Stat label="Prontos" value={formatNumber(summary.data.documents.ready)} /><Stat label="Trechos" value={formatNumber(summary.data.chunks)} hint="Fragmentos disponíveis para busca nos documentos prontos." /><Stat label="Arquivos" value={formatBytes(summary.data.storage_bytes)} hint="Tamanho dos arquivos originais. Não inclui vetores, índices ou o modelo." /></div>
          {summary.data.documents.total > 0 && <section className={styles.card} aria-label="Estado do acervo"><div className={styles.sectionHeader}><h2 className={styles.sectionTitle}>Estado do acervo</h2><span className={styles.muted}>{formatNumber(summary.data.documents.error)} com falha</span></div><LibraryChart spec={{ kind: 'status', values: (['ready', 'processing', 'queued', 'error'] as const).map((key) => ({ label: statusLabels[key], value: summary.data!.documents[key], color: key === 'ready' ? 'success' : key === 'error' ? 'error' : key === 'processing' ? 'warning' : 'info' })) } satisfies ChartSpec} description={`${summary.data.documents.ready} prontos, ${summary.data.documents.processing} indexando, ${summary.data.documents.queued} na fila e ${summary.data.documents.error} com falha.`}><StatusTable counts={summary.data.documents} /></LibraryChart><div className={styles.row}>{(['ready', 'processing', 'queued', 'error'] as const).map((key) => <span key={key} className={styles.row}><Status value={key} /><strong>{formatNumber(summary.data!.documents[key])}</strong></span>)}</div></section>}</> : summary.loading && <Spinner label="Carregando biblioteca" size="small" />}
          <Collection version={version} onChanged={changed} onSelect={(document) => { lastDocument.current = document.id; setSelected(document); }} />
        </>}
        {section === 'indexing' && (summary.data ? <LibraryIndexing summary={summary.data} onSelect={(document) => { lastDocument.current = null; setSelected(document); }} /> : summary.loading && <Spinner label="Carregando indexação" size="small" />)}
        {section === 'performance' && <LibraryPerformance version={version} />}
      </div>
    </div></main>
  </div>;
}
function StatusTable({ counts }: { counts: Record<'ready' | 'processing' | 'queued' | 'error', number> }) {
  const styles = useLibraryStyles();
  return <table className={styles.dataTable}><caption>Documentos por estado</caption><thead><tr><th>Estado</th><th>Documentos</th></tr></thead><tbody>{(['ready', 'processing', 'queued', 'error'] as const).map((key) => <tr key={key}><td>{statusLabels[key]}</td><td>{formatNumber(counts[key])}</td></tr>)}</tbody></table>;
}
function Collection({ version, onChanged, onSelect }: { version: number; onChanged: () => void; onSelect: (document: { id: string; name: string }) => void }) {
  const styles = useLibraryStyles();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<LibraryStatus>('');
  const [sort, setSort] = useState<LibrarySort>('newest');
  const [page, setPage] = useState(1);
  useEffect(() => { const timer = setTimeout(() => { setSearch(query.trim()); setPage(1); }, 300); return () => clearTimeout(timer); }, [query]);
  const loader = useCallback((signal: AbortSignal) => libraryApi.documents({ q: search, status, sort, page }, signal), [search, status, sort, page]);
  const { data, error, loading } = useRemote(loader, version);
  useEffect(() => { if (data) { const last = Math.max(1, Math.ceil(data.total / data.page_size)); if (page > last) setPage(last); } }, [data, page]);
  return <section className={styles.card} aria-labelledby="library-files-title"><div className={styles.sectionHeader}><h2 className={styles.sectionTitle} id="library-files-title">Arquivos</h2>{loading && <Spinner size="tiny" aria-label="Atualizando arquivos" />}</div>
    <div className={styles.filters}><Field label="Buscar arquivo"><Input contentBefore={<SearchRegular />} value={query} maxLength={200} onChange={(_, value) => setQuery(value.value)} placeholder="Nome do arquivo" /></Field><Field label="Estado"><Select value={status} onChange={(_, value) => { setStatus(value.value as LibraryStatus); setPage(1); }}><option value="">Todos</option><option value="ready">Prontos</option><option value="processing">Indexando</option><option value="queued">Na fila</option><option value="error">Com falha</option></Select></Field><Field label="Ordenar por"><Select value={sort} onChange={(_, value) => { setSort(value.value as LibrarySort); setPage(1); }}><option value="newest">Mais recentes</option><option value="name">Nome</option><option value="size">Maior arquivo</option><option value="chunks">Mais trechos</option></Select></Field></div>
    <LibraryError message={error} />
    {data && !error && <><div className={styles.documentList} aria-busy={loading}>{data.documents.map((document) => <article className={styles.document} key={document.id}><div className={styles.documentMain}><DocumentRegular className={styles.documentIcon} aria-hidden /><div style={{ minWidth: 0 }}><Button id={`library-document-${document.id}`} appearance="transparent" className={styles.documentName} onClick={() => onSelect(document)}>{document.name}</Button><div className={styles.documentMeta}><span>{document.extension.toUpperCase().replace('.', '')}</span><span>{formatBytes(document.size_bytes)}</span><span>{formatNumber(document.chunk_count)} trechos</span><time dateTime={document.created_at}>{formatDate(document.created_at)}</time></div></div></div><div className={styles.documentActions}><Status value={document.status} /><DocumentActions document={document} onChange={onChanged} /></div></article>)}</div>{!data.documents.length && <Empty>{search || status ? 'Nenhum arquivo corresponde aos filtros.' : 'Envie seu primeiro arquivo pela biblioteca da conversa.'}</Empty>}<Pager page={page} total={data.total} size={data.page_size} disabled={loading} onChange={setPage} /></>}
  </section>;
}
