import { useEffect, useRef, useState, type ReactElement } from 'react';
import {
  Badge, Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle,
  Field, Input, MessageBar, MessageBarActions, MessageBarBody, MessageBarTitle,
  Select, Spinner, Tab, TabList, makeStyles, tokens,
} from '@fluentui/react-components';
import {
  ArrowLeftRegular, ArrowClockwiseRegular, ArrowUndoRegular, CheckmarkCircleRegular,
  DatabaseRegular, DocumentSettingsRegular, GaugeRegular, PeopleRegular, SaveRegular,
  SearchRegular, SettingsRegular, SparkleRegular,
} from '@fluentui/react-icons';
import { errorMessage } from './api';
import AppearanceMenu from './AppearanceMenu';
import { formatBytes } from './storage';
import {
  changedSettings, draftValues, numericFields, SettingsApiError, settingsApi, settingsGroups, toDraft, validateSettings,
  type InstalledModel, type NumericSettingsKey, type SettingsDraft, type SettingsErrors, type SettingsGroup, type SettingsKey, type SettingsSnapshot,
} from './settings';

const useSettingsStyles = makeStyles({
  page: { height: '100dvh', minHeight: '480px', display: 'flex', flexDirection: 'column', color: tokens.colorNeutralForeground1, backgroundColor: tokens.colorNeutralBackground2, fontFamily: tokens.fontFamilyBase },
  header: { display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalL, padding: `${tokens.spacingVerticalL} ${tokens.spacingHorizontalXXL}`, backgroundColor: tokens.colorNeutralBackground1, borderBottom: `1px solid ${tokens.colorNeutralStroke2}`, flexWrap: 'wrap', '@media (max-width: 600px)': { padding: tokens.spacingHorizontalM, gap: tokens.spacingHorizontalM } },
  back: { minWidth: '44px', minHeight: '44px' },
  backText: { '@media (max-width: 600px)': { display: 'none' } },
  title: { margin: 0, fontSize: tokens.fontSizeBase500, lineHeight: tokens.lineHeightBase500, fontWeight: tokens.fontWeightSemibold },
  headerBrand: { display: 'flex', gap: tokens.spacingHorizontalS, alignItems: 'center', '& svg': { color: tokens.colorBrandForeground1, fontSize: tokens.fontSizeBase500 } },
  headerActions: { marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalM },
  headerBadge: { '@media (max-width: 600px)': { display: 'none' } },
  scroll: { flex: 1, minHeight: 0, overflowY: 'auto', scrollbarGutter: 'stable' },
  container: { width: '100%', maxWidth: '1216px', margin: '0 auto', padding: tokens.spacingHorizontalXXL, display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXL, '@media (max-width: 600px)': { padding: tokens.spacingHorizontalM, gap: tokens.spacingVerticalL } },
  intro: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, '& p': { margin: 0, color: tokens.colorNeutralForeground2, lineHeight: tokens.lineHeightBase400, maxWidth: '780px' } },
  introTitle: { margin: 0, fontSize: tokens.fontSizeBase600, lineHeight: tokens.lineHeightBase600, fontWeight: tokens.fontWeightSemibold, letterSpacing: '-0.5px', '@media (max-width: 600px)': { fontSize: tokens.fontSizeBase500, lineHeight: tokens.lineHeightBase500 } },
  shared: { display: 'flex', alignItems: 'flex-start', gap: tokens.spacingHorizontalM, padding: tokens.spacingHorizontalL, backgroundColor: tokens.colorBrandBackground2, color: tokens.colorBrandForeground2, border: `1px solid ${tokens.colorBrandStroke2}`, borderRadius: tokens.borderRadiusLarge, '& > svg': { flexShrink: 0, fontSize: tokens.fontSizeBase500 }, '& p': { margin: 0, lineHeight: tokens.lineHeightBase300 }, '& strong': { display: 'block', marginBottom: tokens.spacingVerticalXXS } },
  layout: { display: 'grid', gridTemplateColumns: '224px minmax(0, 1fr)', gap: tokens.spacingHorizontalXXL, alignItems: 'start', '@media (max-width: 900px)': { gridTemplateColumns: 'minmax(0, 1fr)', gap: tokens.spacingVerticalL } },
  navigation: { position: 'sticky', top: tokens.spacingVerticalXL, display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, '@media (max-width: 900px)': { display: 'none' } },
  navLabel: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3, fontWeight: tokens.fontWeightSemibold, paddingLeft: tokens.spacingHorizontalM },
  tabs: { alignItems: 'stretch' },
  tab: { justifyContent: 'flex-start', minHeight: '48px', '& span': { whiteSpace: 'normal' } },
  mobileNavigation: { display: 'none', '@media (max-width: 900px)': { display: 'block' } },
  section: { minWidth: 0 },
  sectionHeader: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS, marginBottom: tokens.spacingVerticalL, '& h2': { margin: 0, fontSize: tokens.fontSizeBase500, lineHeight: tokens.lineHeightBase500, fontWeight: tokens.fontWeightSemibold }, '& p': { margin: 0, color: tokens.colorNeutralForeground2, lineHeight: tokens.lineHeightBase400 } },
  effect: { fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3, lineHeight: tokens.lineHeightBase300, margin: `${tokens.spacingVerticalS} 0 ${tokens.spacingVerticalL}` },
  stack: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL, minWidth: 0 },
  card: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL, padding: tokens.spacingHorizontalXL, border: `1px solid ${tokens.colorNeutralStroke2}`, borderRadius: tokens.borderRadiusLarge, backgroundColor: tokens.colorNeutralBackground1, minWidth: 0, '@media (max-width: 600px)': { padding: tokens.spacingHorizontalL } },
  cardHeading: { margin: 0, fontSize: tokens.fontSizeBase400, lineHeight: tokens.lineHeightBase400, fontWeight: tokens.fontWeightSemibold },
  cardDescription: { margin: 0, color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200, lineHeight: tokens.lineHeightBase300 },
  fieldGrid: { display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', columnGap: tokens.spacingHorizontalXL, rowGap: tokens.spacingVerticalXXL, '@media (max-width: 700px)': { gridTemplateColumns: 'minmax(0, 1fr)' } },
  field: { minWidth: 0 },
  input: { width: '100%', maxWidth: '270px' },
  select: { width: '100%', maxWidth: '480px' },
  suffix: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  modelInfo: { display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalS, alignItems: 'center' },
  fixed: { display: 'flex', alignItems: 'flex-start', gap: tokens.spacingHorizontalM, padding: tokens.spacingHorizontalL, borderRadius: tokens.borderRadiusMedium, backgroundColor: tokens.colorNeutralBackground3, '& > svg': { flexShrink: 0, fontSize: tokens.fontSizeBase500, color: tokens.colorBrandForeground1 }, '& strong': { display: 'block', marginBottom: tokens.spacingVerticalXS }, '& p': { margin: 0, fontSize: tokens.fontSizeBase200, lineHeight: tokens.lineHeightBase300, color: tokens.colorNeutralForeground2 } },
  footer: { flexShrink: 0, borderTop: `1px solid ${tokens.colorNeutralStroke2}`, backgroundColor: tokens.colorNeutralBackground1, padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalXXL}`, '@media (max-width: 600px)': { padding: tokens.spacingHorizontalM } },
  footerInner: { maxWidth: '1168px', margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: tokens.spacingHorizontalL, flexWrap: 'wrap' },
  footerStatus: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalXXS, '& small': { color: tokens.colorNeutralForeground3, lineHeight: tokens.lineHeightBase200 } },
  footerActions: { display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalS, '& button': { minHeight: '40px' } },
  loading: { padding: tokens.spacingHorizontalXXXL, display: 'flex', justifyContent: 'center' },
  messageActions: { flexWrap: 'wrap' },
  validationLinks: { display: 'flex', gap: tokens.spacingHorizontalS, flexWrap: 'wrap', marginTop: tokens.spacingVerticalS },
});

const groupIcons: Record<SettingsGroup, ReactElement> = { answers: <SparkleRegular />, performance: <GaugeRegular />, retrieval: <SearchRegular />, ingestion: <DocumentSettingsRegular /> };

export default function SettingsPage({ onBack, onSaved }: { onBack: () => void; onSaved: () => void }) {
  const styles = useSettingsStyles();
  const [snapshot, setSnapshot] = useState<SettingsSnapshot | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [models, setModels] = useState<InstalledModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [group, setGroup] = useState<SettingsGroup>('answers');
  const [notice, setNotice] = useState<{ kind: 'error' | 'warning' | 'success' | 'info'; title: string; message: string; conflict?: boolean } | null>(null);
  const [serverErrors, setServerErrors] = useState<SettingsErrors>({});
  const [showValidation, setShowValidation] = useState(false);
  const [confirm, setConfirm] = useState<'leave' | 'reload' | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const dialogReturnRef = useRef<HTMLElement | null>(null);
  const mountedRef = useRef(true);
  const requestRef = useRef<AbortController | null>(null);
  const changed = draft && snapshot ? changedSettings(draft, snapshot.values) : [];
  const dirty = changed.length > 0;
  const localErrors = draft ? validateSettings(draft) : {};
  const errors = { ...(showValidation ? localErrors : {}), ...serverErrors };
  const invalidGroups = settingsGroups.filter(({ key }) => key === 'answers' && errors.ollama_model || numericFields[key].some(({ key: name }) => errors[name]));

  const load = async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    try {
      const next = await settingsApi.get(controller.signal);
      if (controller.signal.aborted) return;
      setSnapshot(next); setDraft(toDraft(next.values)); setServerErrors({}); setShowValidation(false); setNotice(null);
    } catch (cause) {
      if (!controller.signal.aborted) setNotice({ kind: 'error', title: 'Configurações indisponíveis', message: errorMessage(cause) });
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };

  const loadModels = async () => {
    setModelsLoading(true); setModelsError('');
    try { const result = await settingsApi.models(); if (mountedRef.current) setModels(result.models); }
    catch (cause) { if (mountedRef.current) setModelsError(errorMessage(cause)); }
    finally { if (mountedRef.current) setModelsLoading(false); }
  };

  useEffect(() => {
    mountedRef.current = true;
    void load(); void loadModels(); headingRef.current?.focus();
    return () => { mountedRef.current = false; requestRef.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!dirty) return;
    const preventExit = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', preventExit);
    return () => window.removeEventListener('beforeunload', preventExit);
  }, [dirty]);

  const openConfirm = (action: 'leave' | 'reload') => {
    dialogReturnRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setConfirm(action);
  };

  const closeConfirm = () => {
    setConfirm(null);
    requestAnimationFrame(() => {
      if (dialogReturnRef.current?.isConnected) dialogReturnRef.current.focus();
      else headingRef.current?.focus();
    });
  };

  const edit = (key: SettingsKey, value: string) => {
    setDraft((previous) => previous ? { ...previous, [key]: value } : previous);
    setServerErrors((previous) => { const next = { ...previous }; delete next[key]; return next; });
    setNotice((previous) => previous?.kind === 'success' || previous?.kind === 'info' ? null : previous);
  };

  const showErrorField = (validation: SettingsErrors) => {
    const first = Object.keys(validation)[0] as SettingsKey | undefined;
    const destination = first === 'ollama_model' ? 'answers' : settingsGroups.find(({ key }) => numericFields[key].some((field) => field.key === first))?.key;
    if (destination) setGroup(destination);
    requestAnimationFrame(() => { if (first) document.getElementById(`setting-${first}`)?.focus(); });
  };

  const save = async () => {
    if (!draft || !snapshot || saving || !dirty) return;
    setShowValidation(true);
    const validation = validateSettings(draft);
    if (Object.keys(validation).length) { showErrorField(validation); return; }
    setSaving(true); setServerErrors({}); setNotice(null);
    try {
      const next = await settingsApi.save(snapshot.revision, draftValues(draft));
      setSnapshot(next); setDraft(toDraft(next.values)); setShowValidation(false);
      setNotice({ kind: 'success', title: 'Configurações salvas', message: 'Os novos valores já estão disponíveis para as próximas respostas e ingestões.' });
      onSaved();
    } catch (cause) {
      if (cause instanceof SettingsApiError && cause.status === 409) {
        const busy = cause.code === 'runtime_busy' || /ocupad|andamento|aguard|busy/i.test(cause.message);
        setNotice({ kind: 'warning', title: busy ? 'Aguarde a operação em andamento' : 'As configurações mudaram', message: busy ? 'Há uma resposta ou ingestão em andamento. Aguarde a conclusão e tente salvar novamente. Seus ajustes foram preservados.' : 'Outra aba ou pessoa salvou novos valores. Seus ajustes continuam aqui. Recarregue os valores atuais antes de editar novamente.', conflict: !busy });
      } else {
        const fieldErrors = cause instanceof SettingsApiError ? cause.fieldErrors : {};
        setServerErrors(fieldErrors); if (Object.keys(fieldErrors).length) showErrorField(fieldErrors);
        setNotice({ kind: 'error', title: 'Não foi possível salvar', message: errorMessage(cause) });
      }
    } finally { setSaving(false); }
  };

  const renderField = (key: NumericSettingsKey) => {
    const field = numericFields[group].find((item) => item.key === key)!;
    return <Field key={key} className={styles.field} label={field.label} hint={`${field.hint} · De ${field.min.toLocaleString('pt-BR')} a ${field.max.toLocaleString('pt-BR')}${field.unit ? ` ${field.unit}` : ''}`} validationState={errors[key] ? 'error' : 'none'} validationMessage={errors[key]}>
      <Input id={`setting-${key}`} className={styles.input} type="number" value={draft![key]} min={field.min} max={field.max} step={field.step || 1} disabled={saving || loading} contentAfter={field.unit ? <span className={styles.suffix}>{field.unit}</span> : undefined} onChange={(_, data) => edit(key, data.value)} />
    </Field>;
  };

  const card = (title: string, fields: NumericSettingsKey[], description?: string) => <section className={styles.card} aria-label={title}>
    <h3 className={styles.cardHeading}>{title}</h3>
    {description && <p className={styles.cardDescription}>{description}</p>}
    <div className={styles.fieldGrid}>{fields.map(renderField)}</div>
  </section>;

  const availableModels = [...new Set([snapshot?.values.ollama_model, draft?.ollama_model, ...models.map((model) => model.name)].filter((name): name is string => !!name))];
  const selectedModel = models.find((model) => model.name === draft?.ollama_model);
  const currentGroup = settingsGroups.find(({ key }) => key === group)!;
  const savedAt = snapshot?.updated_at ? new Date(snapshot.updated_at).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : null;

  return <div className={styles.page}>
    <header className={styles.header}>
      <Button className={styles.back} icon={<ArrowLeftRegular />} appearance="subtle" aria-label="Voltar ao chat" disabled={saving} onClick={() => dirty ? openConfirm('leave') : onBack()}><span className={styles.backText}>Voltar ao chat</span></Button>
      <div className={styles.headerBrand}><SettingsRegular aria-hidden /><h1 className={styles.title} tabIndex={-1} ref={headingRef}>Configurações</h1></div>
      <div className={styles.headerActions}><Badge className={styles.headerBadge} appearance="tint" color="informative" icon={<PeopleRegular />}>Acesso compartilhado</Badge><AppearanceMenu /></div>
    </header>
    <main className={styles.scroll}>
      <div className={styles.container}>
        <div className={styles.intro}><h2 className={styles.introTitle}>Ajuste a IA ao seu ambiente.</h2><p>Escolha como o Mini RAG responde, consulta arquivos e usa a CPU. Esses ajustes controlam a execução da IA; não treinam nem alteram os pesos do modelo.</p></div>
        <div className={styles.shared}><PeopleRegular aria-hidden /><div><strong>Configurações globais, sem conta de acesso</strong><p>Estas configurações são compartilhadas e afetam todas as conversas e uploads.</p></div></div>
        {notice && <MessageBar intent={notice.kind}><MessageBarBody><MessageBarTitle>{notice.title}</MessageBarTitle>{notice.message}</MessageBarBody>
          <MessageBarActions className={styles.messageActions}>{notice.conflict ? <Button size="small" onClick={() => dirty ? openConfirm('reload') : void load()}>Recarregar valores atuais</Button> : notice.kind === 'error' && notice.title === 'Configurações indisponíveis' ? <Button size="small" disabled={loading} onClick={() => { void load(); }}>Tentar novamente</Button> : notice.kind === 'error' || notice.kind === 'warning' ? <Button size="small" disabled={saving || !dirty} onClick={() => { void save(); }}>Tentar salvar novamente</Button> : <Button size="small" appearance="subtle" onClick={() => setNotice(null)}>Dispensar</Button>}</MessageBarActions>
        </MessageBar>}
        {loading && !snapshot ? <div className={styles.loading}><Spinner label="Carregando configurações" /></div> : draft && snapshot && <form noValidate id="settings-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
          {invalidGroups.length > 0 && <MessageBar intent="error"><MessageBarBody><MessageBarTitle>Revise os parâmetros indicados</MessageBarTitle>Há valores inválidos em {invalidGroups.length === 1 ? 'uma seção' : `${invalidGroups.length} seções`}.<div className={styles.validationLinks}>{invalidGroups.map((item) => <Button key={item.key} size="small" onClick={() => setGroup(item.key)}>{item.label}</Button>)}</div></MessageBarBody></MessageBar>}
          <div className={styles.layout}>
            <div className={styles.navigation}><span className={styles.navLabel}>AJUSTAR POR OBJETIVO</span><TabList vertical className={styles.tabs} selectedValue={group} onTabSelect={(_, data) => setGroup(data.value as SettingsGroup)} aria-label="Objetivo da configuração">{settingsGroups.map((item) => <Tab className={styles.tab} id={`tab-${item.key}`} aria-controls={`panel-${item.key}`} icon={groupIcons[item.key]} key={item.key} value={item.key}>{item.label}{numericFields[item.key].some(({ key }) => errors[key]) || item.key === 'answers' && errors.ollama_model ? ' · revisar' : ''}</Tab>)}</TabList></div>
            <div className={styles.mobileNavigation}><Field label="Objetivo da configuração"><Select value={group} onChange={(_, data) => setGroup(data.value as SettingsGroup)}>{settingsGroups.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</Select></Field></div>
            {settingsGroups.map((item) => <div hidden={item.key !== group} key={item.key} id={`panel-${item.key}`} role="tabpanel" aria-labelledby={`tab-${item.key}`} className={styles.section} tabIndex={0}>
              {item.key === group && <><div className={styles.sectionHeader}><h2>{currentGroup.label}</h2><p>{currentGroup.description}</p></div><p className={styles.effect}>{currentGroup.effect}</p><div className={styles.stack}>
                {group === 'answers' && <>
                  <section className={styles.card} aria-label="Modelo local"><h3 className={styles.cardHeading}>Modelo local</h3>
                    {modelsError && <MessageBar intent="warning"><MessageBarBody>{modelsError} Você pode ajustar e salvar os demais parâmetros mantendo o modelo atual.</MessageBarBody><MessageBarActions><Button size="small" disabled={modelsLoading} onClick={() => { void loadModels(); }}>Atualizar lista</Button></MessageBarActions></MessageBar>}
                    <Field label="Modelo de linguagem" hint="Somente modelos já baixados no Ollama. Modelos menores e quantizados costumam exigir menos memória e responder mais rápido na CPU" validationState={errors.ollama_model ? 'error' : 'none'} validationMessage={errors.ollama_model}>
                      <Select className={styles.select} id="setting-ollama_model" value={draft.ollama_model} disabled={saving || loading || modelsLoading} onChange={(_, data) => edit('ollama_model', data.value)}>{availableModels.map((name) => <option key={name} value={name}>{name}{!modelsLoading && !modelsError && !models.some((model) => model.name === name) ? ' (modelo configurado; não encontrado)' : ''}</option>)}</Select>
                    </Field>
                    <div className={styles.modelInfo}>{modelsLoading ? <Spinner size="extra-tiny" label="Consultando modelos instalados" /> : <><Badge appearance="tint" color="informative">Execução local · CPU</Badge>{selectedModel && <span className={styles.cardDescription}>{formatBytes(selectedModel.size_bytes)}{selectedModel.parameter_size ? ` · ${selectedModel.parameter_size}` : ''}{selectedModel.quantization_level ? ` · ${selectedModel.quantization_level}` : ''}</span>}</>}<Button appearance="subtle" size="small" icon={<ArrowClockwiseRegular />} disabled={modelsLoading} onClick={() => { void loadModels(); }}>Atualizar modelos</Button></div>
                  </section>
                  {card('Estilo e extensão', numericFields.answers.map(({ key }) => key))}
                </>}
                {group === 'performance' && <>{card('Memória e contexto', ['context_tokens', 'keep_alive_minutes'])}{card('CPU e tempo de espera', ['cpu_threads', 'generation_batch_size', 'generation_timeout_seconds'])}</>}
                {group === 'retrieval' && <>{card('Seleção das fontes', numericFields.retrieval.map(({ key }) => key))}<div className={styles.fixed}><DatabaseRegular aria-hidden /><div><strong>Embeddings multilíngues · ONNX · CPU · 384 dimensões</strong><p>O modelo de busca permanece fixo para manter os documentos compatíveis com o índice. Os ajustes acima mudam a seleção dos trechos, sem reindexar sua biblioteca.</p></div></div></>}
                {group === 'ingestion' && <>{card('Preparação do texto', ['chunk_tokens', 'chunk_overlap', 'embedding_batch_size'], 'Tokens são unidades de texto, como palavras ou partes delas. O texto é dividido em trechos para gerar os vetores de busca.')}{card('Limites dos documentos', ['max_upload_mb', 'max_documents', 'max_pdf_pages', 'max_text_characters', 'max_docx_uncompressed_mb', 'max_chunks_per_document'], 'Todos os limites se aplicam em conjunto. Elevar apenas o número de páginas pode fazer o arquivo alcançar outro limite. Valores altos aumentam o tempo de ingestão e o consumo de memória.')}</>}
              </div></>}
            </div>)}
          </div>
        </form>}
      </div>
    </main>
    <footer className={styles.footer}><div className={styles.footerInner}>
      <div className={styles.footerStatus}><span role="status">{saving ? 'Salvando configurações…' : dirty ? `${changed.length} ${changed.length === 1 ? 'alteração pendente' : 'alterações pendentes'}` : snapshot ? <><CheckmarkCircleRegular aria-hidden /> Todos os ajustes estão salvos</> : 'Aguardando configurações'}</span><small>{dirty ? 'As alterações só entram em vigor ao salvar.' : savedAt ? `Última atualização: ${savedAt}` : 'Valores iniciais do ambiente.'}</small></div>
      <div className={styles.footerActions}>
        <Button icon={<ArrowClockwiseRegular />} disabled={!snapshot || loading || saving} onClick={() => { setDraft(toDraft(snapshot!.defaults)); setServerErrors({}); setShowValidation(false); setNotice({ kind: 'info', title: 'Padrões carregados para revisão', message: 'Os valores ainda não foram aplicados. Revise e use Salvar alterações para confirmar.' }); }}>Restaurar padrões</Button>
        <Button icon={<ArrowUndoRegular />} disabled={!dirty || loading || saving} onClick={() => { setDraft(toDraft(snapshot!.values)); setServerErrors({}); setShowValidation(false); setNotice(null); }}>Desfazer</Button>
        <Button form="settings-form" type="submit" appearance="primary" icon={saving ? <Spinner size="tiny" aria-hidden /> : <SaveRegular />} disabled={!dirty || loading || saving}>{saving ? 'Salvando…' : 'Salvar alterações'}</Button>
      </div>
    </div></footer>
    <Dialog open={confirm !== null} onOpenChange={(_, data) => { if (!data.open) closeConfirm(); }}>
      <DialogSurface><DialogBody><DialogTitle>{confirm === 'reload' ? 'Recarregar e descartar seus ajustes?' : 'Sair sem salvar?'}</DialogTitle><DialogContent><p>{confirm === 'reload' ? 'Os valores salvos por outra aba ou pessoa substituirão os ajustes pendentes deste formulário.' : 'Você tem alterações pendentes. Ao voltar ao chat, os ajustes que ainda não foram salvos serão descartados.'}</p></DialogContent><DialogActions><Button onClick={closeConfirm}>Continuar editando</Button><Button appearance="primary" onClick={() => { const action = confirm; setConfirm(null); if (action === 'reload') { void load(); headingRef.current?.focus(); } else onBack(); }}>{confirm === 'reload' ? 'Descartar e recarregar' : 'Descartar e voltar'}</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
  </div>;
}
