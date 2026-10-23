import { useCallback, useEffect, useState } from 'react';
import { Badge, Field, InfoLabel, Select, Spinner, Tab, TabList } from '@fluentui/react-components';
import { formatDate, formatDuration, formatNumber, libraryApi } from './library';
import { Empty, LibraryChart, LibraryError, Pager, Stat, useRemote } from './LibraryShared';
import { useLibraryStyles } from './libraryStyles';
import type { ChatMeasurement, ChatOutcome } from './libraryTypes';

type Metric = 'duration_ms' | 'search_ms' | 'first_token_ms' | 'tokens_per_second';
const metricNames: Record<Metric, string> = { duration_ms: 'Resposta', search_ms: 'Busca', first_token_ms: 'Primeiro token', tokens_per_second: 'Velocidade' };
const outcomeLabels: Record<ChatOutcome, string> = { completed: 'Concluída', no_sources: 'Sem fontes', error: 'Falha', cancelled: 'Interrompida' };
export default function LibraryPerformance({ version }: { version: number }) {
  const styles = useLibraryStyles();
  const [model, setModel] = useState('');
  const [operation, setOperation] = useState<'chat' | 'ingestion'>('chat');
  const [metric, setMetric] = useState<Metric>('duration_ms');
  const [page, setPage] = useState(1);
  const loader = useCallback((signal: AbortSignal) => libraryApi.performance(model, signal), [model]);
  const { data, error, loading } = useRemote(loader, version);
  const selectOperation = (value: 'chat' | 'ingestion') => { setOperation(value); setPage(1); };
  const records = operation === 'chat' ? data?.recent_chat : data?.recent_ingestion;
  useEffect(() => { if (records) { const last = Math.max(1, Math.ceil(records.length / 10)); if (page > last) setPage(last); } }, [records, page]);
  const points: [string, number | null][] = operation === 'chat'
    ? (data?.recent_chat ?? []).filter((sample) => sample.outcome === 'completed').map((sample) => [sample.created_at, metric === 'tokens_per_second' ? sample[metric] : sample[metric] == null ? null : sample[metric]! / 1000])
    : (data?.recent_ingestion ?? []).filter((sample) => sample.outcome === 'completed').map((sample) => [sample.created_at, sample.duration_ms / 1000]);
  points.sort((left, right) => Date.parse(left[0]) - Date.parse(right[0]));
  return <><div className={styles.sectionHeader}><TabList aria-label="Operação medida" selectedValue={operation} onTabSelect={(_, value) => selectOperation(value.value as 'chat' | 'ingestion')}><Tab value="chat">Conversas</Tab><Tab value="ingestion">Ingestão</Tab></TabList><div className={styles.row}>{loading && <Spinner size="tiny" label="Atualizando medições" />}<InfoLabel infoButton={{ 'aria-label': 'Informações' }} info="Últimas 500 operações de cada tipo. Medições começam após esta atualização; não incluem texto de conversas ou documentos.">Janela de medição</InfoLabel></div></div>
    <LibraryError message={error} />
    {loading && !data && <Spinner label="Carregando desempenho" size="small" />}
    {data && <>
      {operation === 'chat' && <Field label="Modelo das conversas" style={{ maxWidth: 360 }}><Select value={model} onChange={(_, value) => { setModel(value.value); setPage(1); }}><option value="">Todos os modelos</option>{data.models.map((name) => <option key={name} value={name}>{name}</option>)}</Select></Field>}
      {operation === 'chat' ? <div className={styles.kpis}><Stat label="Resposta · P50" value={formatDuration(data.chat.latency_ms.p50)} hint="Mediana das respostas concluídas. Do início da requisição ao fim da resposta, incluindo espera pela CPU, busca e geração." detail={`P95 ${formatDuration(data.chat.latency_ms.p95)}`} /><Stat label="Primeiro token · P50" value={formatDuration(data.chat.first_token_ms.p50)} hint="Tempo até o primeiro token gerado, incluindo espera pela CPU e busca. Apenas respostas concluídas." detail={`P95 ${formatDuration(data.chat.first_token_ms.p95)}`} /><Stat label="Busca · P50" value={formatDuration(data.chat.search_ms.p50)} hint="Embedding da pergunta e consulta ao índice. Apenas respostas concluídas." detail={`P95 ${formatDuration(data.chat.search_ms.p95)}`} /><Stat label="Geração · P50" value={data.chat.tokens_per_second.p50 == null ? '—' : `${formatNumber(data.chat.tokens_per_second.p50, 1)} tok/s`} hint="Tokens por segundo calculados pelo Ollama ao concluir a geração. Não inclui busca ou fila. Sem dados do servidor, a medição fica indisponível." detail={`${formatNumber(data.chat.completed)} respostas concluídas`} /></div>
        : <div className={styles.kpis}><Stat label="Processamento · P50" value={formatDuration(data.ingestion.duration_ms.p50)} detail={`P95 ${formatDuration(data.ingestion.duration_ms.p95)}`} hint="Extração, tokenização, embeddings e persistência das ingestões concluídas. Não inclui fila ou espera pela CPU." /><Stat label="Trechos por segundo" value={data.ingestion.chunks_per_second.p50 == null ? '—' : formatNumber(data.ingestion.chunks_per_second.p50, 1)} detail="Mediana · P50" hint="Trechos indexados divididos pelo tempo de processamento de cada ingestão concluída." /><Stat label="Concluídas" value={formatNumber(data.ingestion.completed)} /><Stat label="Falhas" value={formatNumber(data.ingestion.error)} /></div>}
      <section className={styles.card}><div className={styles.sectionHeader}><h2 className={styles.sectionTitle}>{operation === 'chat' ? 'Desempenho das respostas' : 'Tempo de ingestão'}</h2>{operation === 'chat' && <Field label="Métrica"><Select value={metric} onChange={(_, value) => setMetric(value.value as Metric)}>{(Object.keys(metricNames) as Metric[]).map((key) => <option key={key} value={key}>{metricNames[key]}</option>)}</Select></Field>}</div>
        {points.some((point) => point[1] != null) ? <LibraryChart spec={{ kind: 'line', points, name: operation === 'chat' ? metricNames[metric] : 'Processamento', unit: operation === 'chat' && metric === 'tokens_per_second' ? 'tok/s' : 's' }} description={`${operation === 'chat' ? metricNames[metric] : 'Tempo de processamento'} das operações concluídas, por data e hora. Pontos sem medição ficam sem valor.`}><table className={styles.dataTable}><caption>{operation === 'chat' ? metricNames[metric] : 'Tempo de ingestão'} por operação concluída</caption><thead><tr><th>Data</th><th>{operation === 'chat' && metric === 'tokens_per_second' ? 'tok/s' : 'Segundos'}</th></tr></thead><tbody>{points.map((point, index) => <tr key={`${point[0]}-${index}`}><td>{formatDate(point[0])}</td><td>{formatNumber(point[1], 2)}</td></tr>)}</tbody></table></LibraryChart> : <Empty>Sem amostras desta métrica. {operation === 'chat' ? 'Conclua uma conversa para medir.' : 'Ingira um arquivo para medir.'}</Empty>}
      </section>
      <section className={styles.card}><div className={styles.sectionHeader}><h2 className={styles.sectionTitle}>{operation === 'chat' ? 'Conversas recentes' : 'Ingestões recentes'}</h2><span className={styles.muted}>{formatNumber(operation === 'chat' ? data.chat.samples : data.ingestion.samples)} amostras{operation === 'ingestion' ? ' · todos os modelos' : ''}</span></div>
        {records?.length ? <><div style={{ overflowX: 'auto' }}><table className={styles.dataTable}><thead><tr><th>Data</th><th>{operation === 'chat' ? 'Modelo' : 'Arquivo'}</th><th>Estado</th><th>Tempo</th>{operation === 'chat' && <th>tok/s</th>}</tr></thead><tbody>{operation === 'chat' ? data.recent_chat.slice((page - 1) * 10, page * 10).map((sample) => <ChatRow key={sample.id} sample={sample} />) : data.recent_ingestion.slice((page - 1) * 10, page * 10).map((sample) => <tr key={sample.id}><td>{formatDate(sample.created_at)}</td><td>{sample.document_name}</td><td><Badge appearance="tint" color={sample.outcome === 'error' ? 'danger' : 'success'}>{sample.outcome === 'error' ? 'Falha' : 'Concluída'}</Badge></td><td>{formatDuration(sample.duration_ms)}</td></tr>)}</tbody></table></div><Pager page={page} total={records.length} size={10} label="operações" onChange={setPage} /></> : <Empty>Sem operações registradas.</Empty>}
      </section>
    </>}
  </>;
}
function ChatRow({ sample }: { sample: ChatMeasurement }) {
  return <tr><td>{formatDate(sample.created_at)}</td><td>{sample.model}</td><td><Badge appearance="tint" color={sample.outcome === 'error' ? 'danger' : sample.outcome === 'completed' ? 'success' : 'informative'}>{outcomeLabels[sample.outcome]}</Badge></td><td>{formatDuration(sample.duration_ms)}</td><td>{formatNumber(sample.tokens_per_second, 1)}</td></tr>;
}
