import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { Badge, Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, DialogTrigger, InfoLabel, MessageBar, MessageBarBody, Spinner } from '@fluentui/react-components';
import { ArrowClockwiseRegular, ArrowLeftRegular, ArrowRightRegular, DeleteRegular, DocumentSearchRegular } from '@fluentui/react-icons';
import { api, errorMessage } from './api';
import { libraryApi, formatNumber } from './library';
import { useLibraryStyles } from './libraryStyles';
import type { ChartSpec } from './LibraryChart';
import type { RagDocument } from './types';

const Chart = lazy(() => import('./LibraryChart'));
export function LibraryChart({ spec, description, children }: { spec: ChartSpec; description: string; children: ReactNode }) {
  const styles = useLibraryStyles();
  return <><Suspense fallback={<Spinner size="small" label="Carregando gráfico" />}><Chart spec={spec} description={description} /></Suspense><details className={styles.dataDetails}><summary>Ver dados do gráfico</summary>{children}</details></>;
}
export function useRemote<T>(loader: (signal: AbortSignal) => Promise<T>, version: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void loader(controller.signal).then((value) => { if (!controller.signal.aborted) setData(value); }).catch((cause) => { if (!controller.signal.aborted) setError(errorMessage(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [loader, version]);
  return { data, error, loading };
}
export function LibraryError({ message }: { message: string }) { return message ? <MessageBar intent="error"><MessageBarBody>{message}</MessageBarBody></MessageBar> : null; }
export function Stat({ label, value, hint, detail }: { label: string; value: string; hint?: string; detail?: string }) {
  const styles = useLibraryStyles();
  return <div className={styles.kpi}><div className={styles.kpiLabel}>{hint ? <InfoLabel infoButton={{ 'aria-label': 'Informações' }} info={hint}>{label}</InfoLabel> : label}</div><strong className={styles.kpiValue}>{value}</strong>{detail && <span className={styles.muted}>{detail}</span>}</div>;
}
export function Empty({ children }: { children: ReactNode }) {
  const styles = useLibraryStyles();
  return <div className={styles.empty}><DocumentSearchRegular aria-hidden /><p>{children}</p></div>;
}
export const statusLabels: Record<RagDocument['status'], string> = { queued: 'Na fila', processing: 'Indexando', ready: 'Pronto', error: 'Falha' };
export function Status({ value }: { value: RagDocument['status'] }) {
  return <Badge appearance="tint" color={value === 'ready' ? 'success' : value === 'error' ? 'danger' : value === 'processing' ? 'warning' : 'informative'}>{statusLabels[value]}</Badge>;
}
export function Pager({ page, total, size, onChange, disabled, label = 'documentos' }: { page: number; total: number; size: number; onChange: (page: number) => void; disabled?: boolean; label?: string }) {
  const styles = useLibraryStyles();
  const pages = Math.max(1, Math.ceil(total / size));
  return <div className={styles.paging}><span className={styles.muted} role="status">{total ? `${formatNumber((page - 1) * size + 1)}–${formatNumber(Math.min(page * size, total))} de ${formatNumber(total)} ${label}` : `0 ${label}`}</span><div className={styles.row}><Button icon={<ArrowLeftRegular />} aria-label={`Página anterior de ${label}`} disabled={disabled || page <= 1} onClick={() => onChange(page - 1)} /><span className={styles.muted}>{page} / {pages}</span><Button icon={<ArrowRightRegular />} aria-label={`Próxima página de ${label}`} disabled={disabled || page >= pages} onClick={() => onChange(page + 1)} /></div></div>;
}
export function DocumentActions({ document, onChange, allowReindex = false }: { document: RagDocument; onChange: (removed?: boolean) => void; allowReindex?: boolean }) {
  const styles = useLibraryStyles();
  const [dialog, setDialog] = useState<'delete' | 'reindex' | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const reindexTrigger = useRef<HTMLButtonElement>(null);
  const deleteTrigger = useRef<HTMLButtonElement>(null);
  const closeDialog = () => {
    const trigger = dialog === 'reindex' ? reindexTrigger.current : deleteTrigger.current;
    setDialog(null); setError(''); requestAnimationFrame(() => trigger?.focus());
  };
  const act = async (action: 'delete' | 'retry' | 'reindex') => {
    setBusy(true); setError('');
    try {
      if (action === 'delete') await api.deleteDocument(document.id);
      else if (action === 'retry') await api.retryDocument(document.id);
      else await libraryApi.reindex(document.id);
      closeDialog(); onChange(action === 'delete');
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <><div className={styles.row}>
    {document.status === 'error' && <Button icon={<ArrowClockwiseRegular />} disabled={busy} onClick={() => { void act('retry'); }}>Tentar novamente</Button>}
    {allowReindex && document.status === 'ready' && <Button ref={reindexTrigger} icon={<ArrowClockwiseRegular />} disabled={busy} onClick={() => { setError(''); setDialog('reindex'); }}>Reindexar</Button>}
    <Dialog open={dialog !== null} onOpenChange={(_, value) => { if (!busy && !value.open) closeDialog(); }}>
      <DialogTrigger disableButtonEnhancement><Button ref={deleteTrigger} className={styles.iconButton} appearance="subtle" icon={<DeleteRegular />} aria-label={`Excluir ${document.name}`} disabled={busy || document.status === 'processing'} onClick={() => { setError(''); setDialog('delete'); }} /></DialogTrigger>
      <DialogSurface><DialogBody><DialogTitle>{dialog === 'reindex' ? 'Reindexar este documento?' : 'Excluir este documento?'}</DialogTitle><DialogContent><p><strong>{document.name}</strong></p><p>{dialog === 'reindex' ? 'O arquivo ficará indisponível na busca até concluir. Usará os ajustes atuais.' : 'O arquivo e seus trechos serão removidos da biblioteca compartilhada.'}</p><LibraryError message={error} /></DialogContent><DialogActions><Button onClick={closeDialog} disabled={busy}>Cancelar</Button><Button appearance="primary" disabled={busy} icon={busy ? <Spinner size="tiny" aria-hidden /> : undefined} onClick={() => { if (dialog) void act(dialog); }}>{dialog === 'reindex' ? 'Reindexar documento' : 'Excluir documento'}</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
  </div>{error && !dialog && <LibraryError message={error} />}</>;
}
