import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import {
  Badge, Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent,
  DialogSurface, DialogTitle, DialogTrigger, ProgressBar, Spinner,
} from '@fluentui/react-components';
import { ArrowClockwiseRegular, DeleteRegular, DocumentRegular, DocumentTextRegular } from '@fluentui/react-icons';
import { api, errorMessage } from './api';
import { formatBytes } from './storage';
import { useStyles } from './styles';
import type { RagDocument, Source } from './types';

const labels: Record<RagDocument['status'], string> = {
  queued: 'Na fila', processing: 'Indexando', ready: 'Pronto', error: 'Falha na ingestão',
};

export function CodeBlock({ children }: { children: ReactNode }) {
  const host = useRef<HTMLPreElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  const measure = useCallback(() => {
    const element = host.current;
    setOverflowing(!!element && element.clientWidth > 0 && element.scrollWidth > element.clientWidth);
  }, []);
  useLayoutEffect(measure, [children, measure]);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(measure);
    observer.observe(host.current);
    return () => observer.disconnect();
  }, [measure]);
  return <pre ref={host} tabIndex={overflowing ? 0 : undefined} role={overflowing ? 'region' : undefined} aria-label={overflowing ? 'Bloco de código' : undefined}>{children}</pre>;
}

export function DocumentCard({ document, selected, disabled, onSelect, onChange }: {
  document: RagDocument; selected: boolean; disabled: boolean;
  onSelect: (checked: boolean) => void; onChange: () => void;
}) {
  const styles = useStyles();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const remove = async () => {
    setBusy(true); setError('');
    try { await api.deleteDocument(document.id); setOpen(false); onChange(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  const retry = async () => {
    setBusy(true); setError('');
    try { await api.retryDocument(document.id); onChange(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  };
  return <article className={styles.document} aria-label={document.name}>
    <div className={styles.documentTop}>
      <DocumentRegular className={styles.documentIcon} aria-hidden />
      <div className={styles.documentInfo}>
        <span className={styles.documentName}>{document.name}</span>
        <span className={styles.small}>{formatBytes(document.size_bytes)}{document.status === 'ready' ? ` · ${document.chunk_count.toLocaleString('pt-BR')} trechos` : ''}</span>
      </div>
      <Dialog open={open} onOpenChange={(_, data) => { if (!busy) { setOpen(data.open); setError(''); } }}>
        <DialogTrigger disableButtonEnhancement>
          <Button className={styles.iconButton} appearance="subtle" icon={<DeleteRegular />} aria-label={`Excluir ${document.name}`} disabled={disabled || busy} />
        </DialogTrigger>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>Excluir este documento?</DialogTitle>
            <DialogContent>
              <p><strong>{document.name}</strong> e todos os seus trechos serão removidos da base. As próximas respostas deixarão de consultar este documento.</p>
              <p className={styles.small}>O arquivo original no seu computador será preservado. Para consultar novamente, envie o arquivo pela biblioteca.</p>
              {error && <p role="alert" className={styles.documentError}>{error}</p>}
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement><Button disabled={busy}>Cancelar</Button></DialogTrigger>
              <Button appearance="primary" icon={busy ? <Spinner size="tiny" aria-hidden /> : <DeleteRegular />} onClick={() => { void remove(); }} disabled={busy}>{busy ? 'Excluindo' : 'Excluir documento'}</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
    <div className={styles.documentBottom}>
      <Badge appearance="tint" color={document.status === 'ready' ? 'success' : document.status === 'error' ? 'danger' : 'informative'} icon={['queued', 'processing'].includes(document.status) ? <Spinner size="extra-tiny" aria-hidden /> : undefined}>{labels[document.status]}</Badge>
      {document.status === 'ready' && <Checkbox label="Usar no chat" checked={selected} disabled={disabled} onChange={(_, data) => onSelect(data.checked === true)} />}
      {document.status === 'error' && <Button size="small" appearance="subtle" icon={<ArrowClockwiseRegular />} onClick={() => { void retry(); }} disabled={busy || disabled}>Tentar novamente</Button>}
    </div>
    {['queued', 'processing'].includes(document.status) && <ProgressBar aria-label={`Ingestão de ${document.name}`} />}
    {document.error && document.status === 'error' && <p className={styles.documentError}>{document.error}</p>}
    {error && !open && <p role="alert" className={styles.documentError}>{error}</p>}
  </article>;
}

export function SourceLink({ source }: { source: Source }) {
  const styles = useStyles();
  return <Dialog>
    <DialogTrigger disableButtonEnhancement>
      <Button appearance="outline" size="small" className={styles.sourceButton} icon={<DocumentTextRegular />}>
        <span className={styles.truncate}>[{source.id}] {source.name}{source.page ? ` · p. ${source.page}` : ''}</span>
      </Button>
    </DialogTrigger>
    <DialogSurface>
      <DialogBody>
        <DialogTitle>Trecho da fonte [{source.id}]</DialogTitle>
        <DialogContent>
          <strong>{source.name}</strong>
          {source.page ? <p className={styles.small}>Página {source.page}</p> : <p className={styles.small}>Documento sem paginação</p>}
          <div className={styles.sourceText}>{source.content}</div>
          <p className={styles.small}>Trecho recuperado da sua biblioteca para esta resposta.</p>
        </DialogContent>
        <DialogActions><DialogTrigger disableButtonEnhancement><Button appearance="primary">Fechar</Button></DialogTrigger></DialogActions>
      </DialogBody>
    </DialogSurface>
  </Dialog>;
}
