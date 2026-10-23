import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge, Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle,
  DialogTrigger, Field, MessageBar, MessageBarBody, MessageBarTitle, Popover, PopoverSurface,
  PopoverTrigger, ProgressBar, Spinner, Textarea, mergeClasses,
} from '@fluentui/react-components';
import {
  AddRegular, ArrowClockwiseRegular, ArrowUploadRegular, ChatRegular, CheckmarkCircleRegular,
  ChevronRightRegular, DatabaseRegular, DeleteRegular, DismissRegular, DocumentAddRegular,
  DocumentSearchRegular, FolderOpenRegular, LeafOneRegular, LockClosedRegular, NavigationRegular,
  PersonRegular, SendRegular, ServerRegular, SettingsRegular, SparkleRegular, StopRegular,
} from '@fluentui/react-icons';
import Markdown from 'react-markdown';
import { api, errorMessage, sendChat, uploadDocument } from './api';
import { DocumentCard, SourceLink } from './components';
import SettingsPage from './SettingsPage';
import { loadConversations, newConversation, STORAGE_KEY } from './storage';
import { useStyles } from './styles';
import type { Conversation, Health, Message, RagDocument } from './types';

function available(status?: string) { return !!status && ['ready', 'ok', 'healthy', 'available', 'loaded'].includes(status); }

export default function App() {
  const styles = useStyles();
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const saved = loadConversations();
    return saved.length ? saved : [newConversation()];
  });
  const [activeId, setActiveId] = useState(() => conversations[0].id);
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState('');
  const [documentsError, setDocumentsError] = useState('');
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectionExplicit, setSelectionExplicit] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(() => window.matchMedia('(min-width: 1001px)').matches);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [generating, setGenerating] = useState(false);
  const [chatStatus, setChatStatus] = useState('');
  const [storageError, setStorageError] = useState(false);
  const [uploading, setUploading] = useState<{ name: string; current: number; total: number; progress: number } | null>(null);
  const [uploadResults, setUploadResults] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const libraryToggleRef = useRef<HTMLButtonElement>(null);
  const settingsToggleRef = useRef<HTMLButtonElement>(null);
  const libraryHeadingRef = useRef<HTMLHeadingElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const activeConversation = conversations.find((item) => item.id === activeId) || conversations[0];
  const readyDocuments = documents.filter((document) => document.status === 'ready');
  const selectedReady = selectedIds.filter((id) => readyDocuments.some((document) => document.id === id));
  const contextDocuments = selectionExplicit ? selectedReady : readyDocuments.map((document) => document.id);
  const modelReady = health && available(health.database.status) && available(health.model.status) && available(health.embedding.status);
  const draftBytes = new TextEncoder().encode(draft.trim()).length;
  const messageTooLong = draftBytes > 1500;
  const uploadLimitMb = health?.limits?.max_upload_mb || 25;
  const canSend = !!draft.trim() && !messageTooLong && !generating && !!modelReady && contextDocuments.length > 0;

  const refreshDocuments = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api.documents(signal);
      setDocuments(result.documents); setDocumentsError('');
    } catch (cause) {
      if (!signal?.aborted) setDocumentsError(errorMessage(cause));
    } finally { if (!signal?.aborted) setLoadingDocuments(false); }
  }, []);

  const refreshHealth = useCallback(async (signal?: AbortSignal) => {
    try { setHealth(await api.health(signal)); setHealthError(''); }
    catch (cause) { if (!signal?.aborted) { setHealth(null); setHealthError(errorMessage(cause)); } }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => { void refreshDocuments(controller.signal); void refreshHealth(controller.signal); };
    refresh();
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 5000);
    const visibility = () => { if (document.visibilityState === 'visible') refresh(); };
    document.addEventListener('visibilitychange', visibility);
    return () => { controller.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', visibility); };
  }, [refreshDocuments, refreshHealth]);

  useEffect(() => () => { abortRef.current?.abort(); }, []);

  useEffect(() => {
    if (libraryOpen && window.matchMedia('(max-width: 1000px)').matches) libraryHeadingRef.current?.focus();
  }, [libraryOpen]);

  useEffect(() => {
    const timer = setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.slice(0, 40))); setStorageError(false); }
      catch { setStorageError(true); }
    }, 400);
    return () => clearTimeout(timer);
  }, [conversations]);

  useEffect(() => {
    if (followRef.current) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'instant' });
  }, [activeConversation.messages, activeId]);

  const updateMessage = useCallback((conversationId: string, messageId: string, update: (message: Message) => Message) => {
    setConversations((previous) => previous.map((conversation) => conversation.id === conversationId ? {
      ...conversation, messages: conversation.messages.map((message) => message.id === messageId ? update(message) : message),
    } : conversation));
  }, []);

  const newChat = () => {
    if (generating) return;
    if (!activeConversation.messages.length) { setNavigationOpen(false); return; }
    const conversation = newConversation();
    setConversations((previous) => [conversation, ...previous].slice(0, 40));
    setActiveId(conversation.id); setDraft(''); setNavigationOpen(false); followRef.current = true;
  };

  const submit = async () => {
    if (!canSend) return;
    const message = draft.trim();
    const conversationId = activeConversation.id;
    const assistantId = crypto.randomUUID();
    const controller = new AbortController();
    abortRef.current = controller;
    const history = activeConversation.messages;
    setConversations((previous) => previous.map((conversation) => conversation.id === conversationId ? {
      ...conversation,
      title: conversation.messages.length ? conversation.title : message.slice(0, 64),
      messages: [...conversation.messages, { id: crypto.randomUUID(), role: 'user', content: message }, { id: assistantId, role: 'assistant', content: '', sources: [] }],
    } : conversation));
    setDraft(''); setGenerating(true); setChatStatus('Consultando seus documentos…'); followRef.current = true;
    try {
      await sendChat(message, history, contextDocuments, (event) => {
        if (event.type === 'sources') {
          updateMessage(conversationId, assistantId, (item) => ({ ...item, sources: event.sources }));
          setChatStatus(event.sources.length ? 'Preparando a resposta na CPU…' : 'Verificando se há informação suficiente…');
        } else if (event.type === 'token') {
          updateMessage(conversationId, assistantId, (item) => ({ ...item, content: item.content + event.content }));
          setChatStatus('Respondendo…');
        } else if (event.type === 'done') {
          updateMessage(conversationId, assistantId, (item) => ({ ...item, state: 'complete' }));
        }
      }, controller.signal);
      setChatStatus('Resposta concluída.');
    } catch (cause) {
      const aborted = controller.signal.aborted;
      updateMessage(conversationId, assistantId, (item) => ({ ...item, state: aborted ? 'interrupted' : 'error', error: aborted ? undefined : errorMessage(cause) }));
      setChatStatus(aborted ? 'Geração interrompida.' : 'Não foi possível concluir a resposta.');
    } finally { setGenerating(false); abortRef.current = null; }
  };

  const upload = async (files: FileList | File[]) => {
    if (uploading) return;
    const queue = Array.from(files);
    if (!queue.length) return;
    const results: string[] = [];
    setUploadResults([]);
    for (let i = 0; i < queue.length; i++) {
      const file = queue[i];
      setUploading({ name: file.name, current: i + 1, total: queue.length, progress: 0 });
      try {
        if (file.size > uploadLimitMb * 1024 * 1024) throw new Error(`O arquivo excede o limite de ${uploadLimitMb} MB.`);
        await uploadDocument(file, (progress) => setUploading((current) => current ? { ...current, progress } : null));
        await refreshDocuments();
      } catch (cause) { results.push(`${file.name}: ${errorMessage(cause)}`); setUploadResults([...results]); }
    }
    setUploading(null);
    if (!results.length) setUploadResults([`${queue.length === 1 ? 'Arquivo enviado' : `${queue.length} arquivos enviados`}. A indexação continuará na biblioteca.`]);
    if (fileRef.current) fileRef.current.value = '';
  };

  const selectDocument = (id: string, checked: boolean) => {
    setSelectedIds((previous) => {
      const base = selectionExplicit ? previous : readyDocuments.map((document) => document.id);
      return checked ? [...new Set([...base, id])] : base.filter((item) => item !== id);
    });
    setSelectionExplicit(true);
  };

  const library = <aside className={styles.library} aria-label="Biblioteca de documentos" id="library">
    <div className={styles.libraryHeading}>
      <div><h2 className={styles.heading} ref={libraryHeadingRef} tabIndex={-1}>Sua biblioteca</h2><span className={styles.small}>O conhecimento por trás das respostas</span></div>
      <Button appearance="subtle" icon={<DismissRegular />} aria-label="Fechar biblioteca" className={styles.iconButton} onClick={() => { setLibraryOpen(false); libraryToggleRef.current?.focus(); }} />
    </div>
    <div className={styles.libraryBody}>
      <div className={mergeClasses(styles.dropzone, dragging && styles.dropzoneActive)} onDragOver={(event) => { event.preventDefault(); if (!uploading) setDragging(true); }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files); }}>
        <ArrowUploadRegular aria-hidden />
        <strong>Adicione seus documentos</strong>
        <span className={styles.small}>Arraste arquivos para cá ou selecione no seu computador.</span>
        <Button icon={<AddRegular />} onClick={() => fileRef.current?.click()} disabled={!!uploading}>Selecionar arquivos</Button>
        <span className={styles.small}>PDF, TXT, MD e DOCX · até {uploadLimitMb} MB por arquivo</span>
        <input ref={fileRef} className={styles.fileInput} type="file" multiple accept=".pdf,.txt,.md,.docx" aria-label="Selecionar arquivos para ingestão" onChange={(event) => { if (event.target.files) void upload(event.target.files); }} />
      </div>
      {uploading && <div className={styles.stack} role="status"><span className={styles.small}>Enviando {uploading.current} de {uploading.total}: <strong>{uploading.name}</strong></span><ProgressBar value={uploading.progress} aria-label={`Envio de ${uploading.name}`} /><span className={styles.small}>{Math.round(uploading.progress * 100)}% enviado</span></div>}
      {uploadResults.length > 0 && <MessageBar intent={uploadResults[0].includes('indexação continuará') ? 'success' : 'error'}><MessageBarBody>{uploadResults.map((result, index) => <div key={index}>{result}</div>)}</MessageBarBody></MessageBar>}
      <div className={styles.librarySubheading}><span className={styles.eyebrow}>Documentos ({documents.length})</span><Button appearance="subtle" size="small" icon={<ArrowClockwiseRegular />} aria-label="Atualizar documentos" onClick={() => { void refreshDocuments(); }} /></div>
      {documentsError && <MessageBar intent="error"><MessageBarBody><MessageBarTitle>Biblioteca indisponível</MessageBarTitle>{documentsError}</MessageBarBody></MessageBar>}
      {loadingDocuments ? <Spinner label="Carregando documentos" size="small" /> : documents.length ? <>
        <span className={styles.small}>{selectionExplicit ? `${selectedReady.length} selecionado${selectedReady.length === 1 ? '' : 's'} para esta conversa` : 'Todos os documentos prontos serão consultados.'}</span>
        {selectionExplicit && <Button appearance="subtle" size="small" onClick={() => { setSelectionExplicit(false); setSelectedIds([]); }} disabled={generating}>Usar todos os documentos</Button>}
        <div className={styles.documentList}>{documents.map((document) => <DocumentCard key={document.id} document={document} selected={!selectionExplicit || selectedIds.includes(document.id)} disabled={generating} onSelect={(checked) => selectDocument(document.id, checked)} onChange={() => { void refreshDocuments(); }} />)}</div>
      </> : !documentsError && <div className={styles.libraryEmpty}><strong>Seu primeiro documento começa aqui.</strong><p>Após o envio, o Mini RAG extrai o texto e prepara os trechos para consulta. Você acompanha cada etapa nesta biblioteca.</p></div>}
    </div>
    <div className={styles.libraryFootnote}><LockClosedRegular aria-hidden /><span>Arquivos e índice ficam no seu ambiente local.</span></div>
  </aside>;

  const openSettings = () => { setNavigationOpen(false); setSettingsOpen(true); };

  return <><div className={styles.app} style={settingsOpen ? { display: 'none' } : undefined}>
    <a href="#main-chat" className={styles.skipLink}>Pular para a conversa</a>
    <nav className={mergeClasses(styles.sidebar, navigationOpen && styles.sidebarOpen)} aria-label="Conversas">
      <div className={styles.brand}><div className={styles.brandIcon}><DocumentSearchRegular aria-hidden /></div><div><div className={styles.brandName}>Mini RAG</div><span className={styles.small}>Seu conhecimento, por perto.</span></div></div>
      <Button icon={<AddRegular />} onClick={newChat} disabled={generating}>Nova conversa</Button>
      <div className={styles.history}>
        <div className={styles.historyHeading}><span className={styles.eyebrow}>Conversas</span><span className={styles.small}>{conversations.length}</span></div>
        {conversations.map((conversation) => <div className={mergeClasses(styles.session, conversation.id === activeId && styles.sessionActive)} key={conversation.id}>
          <Button appearance="transparent" className={styles.sessionButton} icon={<ChatRegular />} aria-current={conversation.id === activeId ? 'page' : undefined} disabled={generating} onClick={() => { setActiveId(conversation.id); setDraft(''); setNavigationOpen(false); followRef.current = true; }}><span className={styles.truncate}>{conversation.title}</span></Button>
          <Dialog>
            <DialogTrigger disableButtonEnhancement><Button appearance="subtle" className={styles.iconButton} icon={<DeleteRegular />} aria-label={`Excluir conversa ${conversation.title}`} disabled={generating} /></DialogTrigger>
            <DialogSurface><DialogBody><DialogTitle>Excluir esta conversa?</DialogTitle><DialogContent><p>“{conversation.title}” será removida do histórico deste navegador. Seus documentos continuarão na biblioteca.</p></DialogContent><DialogActions><DialogTrigger disableButtonEnhancement><Button>Cancelar</Button></DialogTrigger><DialogTrigger disableButtonEnhancement><Button appearance="primary" onClick={() => {
              const remaining = conversations.filter((item) => item.id !== conversation.id);
              const next = remaining.length ? remaining : [newConversation()];
              setConversations(next); if (conversation.id === activeId) { setActiveId(next[0].id); setDraft(''); }
            }}>Excluir conversa</Button></DialogTrigger></DialogActions></DialogBody></DialogSurface>
          </Dialog>
        </div>)}
      </div>
      <Button icon={<SettingsRegular />} appearance="subtle" onClick={openSettings}>Configurações</Button>
      <div className={styles.localCard}><LeafOneRegular aria-hidden /><div><p><strong>Pequeno por escolha.</strong></p><p className={styles.small}>Modelo aberto, execução em CPU e documentos no seu WSL.</p></div></div>
    </nav>
    <div className={styles.workspace}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <Button appearance="subtle" className={mergeClasses(styles.iconButton, styles.mobileMenu)} icon={<NavigationRegular />} aria-label="Mostrar conversas" aria-expanded={navigationOpen} onClick={() => setNavigationOpen(!navigationOpen)} />
          <div className={styles.headerTitle}><h1 className={styles.heading}>Converse com seus documentos</h1><span className={mergeClasses(styles.small, styles.desktopText)}>Respostas com contexto. Fontes para conferir.</span></div>
        </div>
        <div className={styles.headerActions}>
          <Button ref={settingsToggleRef} icon={<SettingsRegular />} appearance="subtle" aria-label="Configurações" onClick={openSettings}><span className={styles.desktopText}>Configurações</span></Button>
          <Popover positioning="below-end">
            <PopoverTrigger disableButtonEnhancement><Button size="small" appearance="subtle" icon={<ServerRegular />} aria-label="Ver status do ambiente local"><Badge appearance="tint" color={modelReady ? 'success' : healthError ? 'danger' : 'warning'}>{modelReady ? 'CPU · pronto' : healthError ? 'Offline' : !health ? 'Conectando' : 'Preparando'}</Badge></Button></PopoverTrigger>
            <PopoverSurface><div className={styles.healthGrid}><strong>Ambiente local</strong><div className={styles.healthRow}><DatabaseRegular aria-hidden /><div><p>PostgreSQL · {health?.database.status || 'sem conexão'}</p><code>{health?.database.version}</code></div></div><div className={styles.healthRow}><ServerRegular aria-hidden /><div><p>Modelo · {health?.model.status || 'desconhecido'}</p><code>{health?.model.name || 'Aguardando o servidor'}</code></div></div><div className={styles.healthRow}><DocumentSearchRegular aria-hidden /><div><p>Embeddings · {health?.embedding.status || 'desconhecido'}</p><code>{health?.embedding.name || 'Aguardando o servidor'}</code></div></div><Button icon={<ArrowClockwiseRegular />} onClick={() => { void refreshHealth(); }}>Verificar conexão</Button></div></PopoverSurface>
          </Popover>
          <Button ref={libraryToggleRef} icon={<FolderOpenRegular />} appearance={libraryOpen ? 'secondary' : 'outline'} aria-label="Biblioteca de documentos" aria-expanded={libraryOpen} aria-controls="library" onClick={() => setLibraryOpen(!libraryOpen)}><span className={styles.desktopText}>Biblioteca</span><span aria-hidden className={styles.libraryCount}>{documents.length}</span></Button>
        </div>
      </header>
      <div className={styles.content}>
        <main id="main-chat" className={mergeClasses(styles.chatPane, libraryOpen && styles.chatHiddenMobile)} tabIndex={-1}>
          <div className={styles.notices}>
            {healthError && <MessageBar intent="error"><MessageBarBody><MessageBarTitle>O servidor local está indisponível</MessageBarTitle>Confira se os serviços estão em execução. A conexão será verificada automaticamente.</MessageBarBody></MessageBar>}
            {health && !modelReady && <MessageBar intent="warning"><MessageBarBody><MessageBarTitle>O ambiente está se preparando</MessageBarTitle>{health.model.status === 'missing' ? 'O modelo está sendo preparado. O primeiro download pode levar alguns minutos.' : health.embedding.status === 'loading' ? 'Os embeddings estão sendo carregados. Você já pode organizar seus arquivos.' : 'Consulte o status do ambiente para verificar o modelo, os embeddings e o banco.'}</MessageBarBody></MessageBar>}
            {storageError && <MessageBar intent="warning"><MessageBarBody>O armazenamento deste navegador está cheio ou indisponível. O histórico atual ficará apenas nesta aba.</MessageBarBody></MessageBar>}
          </div>
          <div className={styles.scroll} ref={scrollRef} onScroll={(event) => { const element = event.currentTarget; followRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 100; }}>
            {!activeConversation.messages.length ? <div className={styles.empty}>
              <div className={styles.heroIcon}><SparkleRegular aria-hidden /></div>
              <span className={styles.eyebrow}>Sua base de conhecimento local</span>
              <h2 className={styles.heroTitle}>Boas perguntas.<br />Respostas nos seus arquivos.</h2>
              <p className={styles.heroDescription}>Reúna seus documentos e transforme informação em conversa. O Mini RAG busca os trechos relevantes e mostra de onde veio cada resposta.</p>
              <div className={styles.steps}>
                <div className={styles.stepCard}><DocumentAddRegular aria-hidden /><strong>1. Construa sua biblioteca</strong><p>Envie documentos e aguarde o status “Pronto”.</p><Button appearance="subtle" size="small" icon={<ChevronRightRegular />} iconPosition="after" onClick={() => setLibraryOpen(true)}>Abrir biblioteca</Button></div>
                <div className={styles.stepCard}><ChatRegular aria-hidden /><strong>2. Comece uma conversa</strong><p>{readyDocuments.length ? `${readyDocuments.length} documento${readyDocuments.length === 1 ? '' : 's'} pronto${readyDocuments.length === 1 ? '' : 's'}. Faça sua primeira pergunta abaixo.` : 'Pergunte, compare ideias e confira os trechos usados como fonte.'}</p><Badge appearance="tint" color={readyDocuments.length ? 'success' : 'informative'} icon={readyDocuments.length ? <CheckmarkCircleRegular /> : undefined}>{readyDocuments.length ? 'Biblioteca preparada' : 'Aguardando documentos'}</Badge></div>
              </div>
            </div> : <div className={styles.conversation} aria-label="Mensagens da conversa">{activeConversation.messages.map((message, index) => {
              const pending = generating && index === activeConversation.messages.length - 1;
              return <article className={styles.message} key={message.id} aria-label={message.role === 'user' ? 'Sua mensagem' : 'Resposta do Mini RAG'}>
                <div className={mergeClasses(styles.messageIcon, message.role === 'user' && styles.userIcon)}>{message.role === 'user' ? <PersonRegular aria-hidden /> : <SparkleRegular aria-hidden />}</div>
                <div className={styles.messageBody}><span className={styles.messageLabel}>{message.role === 'user' ? 'Você' : 'Mini RAG'}</span>
                  {message.role === 'user' ? <p className={styles.userText}>{message.content}</p> : <>
                    <div className={styles.markdown}><Markdown skipHtml disallowedElements={['img', 'iframe', 'script', 'style']} components={{ a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{message.content}</Markdown></div>
                    {pending && <div className={styles.answerStatus}><Spinner size="extra-tiny" />{chatStatus}</div>}
                    {message.state === 'error' && <MessageBar intent="error"><MessageBarBody>{message.error}</MessageBarBody></MessageBar>}
                    {message.state === 'interrupted' && <p className={styles.answerStatus}><StopRegular aria-hidden />Geração interrompida. A resposta pode estar incompleta.</p>}
                    {!!message.sources?.length && <div className={styles.sources} aria-label="Fontes consultadas">{message.sources.map((source) => <SourceLink key={`${source.document_id}-${source.id}`} source={source} />)}</div>}
                  </>}
                </div>
              </article>;
            })}</div>}
          </div>
          <div className={styles.composerArea}>
            <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
              <div className={styles.composerContext}><DocumentSearchRegular aria-hidden /><span>{contextDocuments.length ? `Consultando ${contextDocuments.length === 1 ? '1 documento' : `${contextDocuments.length} documentos`}${selectionExplicit ? ' selecionado' + (contextDocuments.length > 1 ? 's' : '') : ''}` : readyDocuments.length ? 'Selecione ao menos um documento na biblioteca' : 'Adicione um documento para começar'}</span></div>
              <Field label="Sua pergunta" size="small" validationState={messageTooLong ? 'error' : 'none'} validationMessage={messageTooLong ? 'Reduza sua pergunta para até 1.500 bytes. Acentos podem ocupar mais de um byte.' : undefined}>
                <Textarea className={styles.composerTextarea} appearance="outline" placeholder="O que você quer descobrir nos seus documentos?" value={draft} maxLength={2000} disabled={generating} resize="vertical" onChange={(_, data) => setDraft(data.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} />
              </Field>
              <div className={styles.composerFooter}><span className={styles.composerHint}>Enter para enviar · Shift + Enter para uma nova linha{draftBytes > 1200 ? ` · ${draftBytes}/1.500 bytes` : ''}</span>{generating ? <Button appearance="primary" icon={<StopRegular />} onClick={() => abortRef.current?.abort()}>Interromper</Button> : <Button appearance="primary" type="submit" icon={<SendRegular />} disabled={!canSend}>Enviar</Button>}</div>
            </form>
            <p className={styles.composerDisclaimer}>A IA pode cometer erros. Confira as fontes antes de usar a resposta.</p>
            <div role="status" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clipPath: 'inset(50%)' }}>{generating ? 'Gerando resposta.' : chatStatus}</div>
          </div>
        </main>
        {libraryOpen && library}
      </div>
    </div>
  </div>{settingsOpen && <SettingsPage onBack={() => { setSettingsOpen(false); requestAnimationFrame(() => settingsToggleRef.current?.focus()); }} onSaved={() => { void refreshHealth(); }} />}</>;
}
