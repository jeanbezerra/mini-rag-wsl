import { useEffect, useRef } from 'react';
import { init, use, type EChartsCoreOption } from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import { LabelLayout } from 'echarts/features';
import { useLibraryStyles } from './libraryStyles';
import { useAppearance } from './AppearanceProvider';

use([BarChart, LineChart, AriaComponent, GridComponent, TooltipComponent, SVGRenderer, LabelLayout]);

export type ChartSpec =
  | { kind: 'bars'; labels: string[]; values: number[]; name: string; horizontal?: boolean }
  | { kind: 'line'; points: [string, number | null][]; name: string; unit: string }
  | { kind: 'status'; values: { label: string; value: number; color: 'success' | 'error' | 'warning' | 'info' }[] };

export default function LibraryChart({ spec, description }: { spec: ChartSpec; description: string }) {
  const styles = useLibraryStyles();
  const { resolvedTheme } = useAppearance();
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const element = host.current;
    const css = getComputedStyle(element);
    const color = (key: string) => css.getPropertyValue(`--library-chart-${key}`).trim();
    const number = (value: number) => value.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
    const option: EChartsCoreOption = {
      animation: false,
      textStyle: { fontFamily: css.fontFamily, color: color('text'), fontSize: 12 },
      color: [color('brand')],
      aria: { enabled: true, label: { description }, decal: { show: false } },
      tooltip: { trigger: 'axis', confine: true, backgroundColor: color('bg'), borderColor: color('grid'), textStyle: { color: color('text') }, valueFormatter: (value: unknown) => typeof value === 'number' ? number(value) : String(value ?? '—'), renderMode: 'richText' },
      grid: { top: 16, bottom: 12, left: 8, right: 24, containLabel: true },
    };
    const valueAxis = { type: 'value', min: 0, axisLabel: { color: color('muted'), formatter: number }, splitLine: { lineStyle: { color: color('grid'), type: 'dashed' } } };
    if (spec.kind === 'bars') {
      const categories = { type: 'category', data: spec.labels, inverse: !!spec.horizontal, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: color('text'), width: spec.horizontal ? 110 : 70, overflow: 'truncate', interval: 0 } };
      option.xAxis = spec.horizontal ? valueAxis : categories;
      option.yAxis = spec.horizontal ? categories : valueAxis;
      option.series = [{ type: 'bar', name: spec.name, data: spec.values, barMaxWidth: 26, itemStyle: { borderRadius: spec.horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] }, emphasis: { disabled: true } }];
    } else if (spec.kind === 'line') {
      const times = spec.points.map(([time]) => Date.parse(time));
      const spansDays = times.length > 1 && Math.max(...times) - Math.min(...times) >= 86400000;
      option.xAxis = { type: 'time', axisTick: { show: false }, axisLine: { show: false }, splitNumber: 4, axisLabel: { color: color('muted'), hideOverlap: true, formatter: (value: number) => new Date(value).toLocaleString('pt-BR', { ...(spansDays ? { day: '2-digit', month: '2-digit' } as const : {}), hour: '2-digit', minute: '2-digit' }) } };
      option.yAxis = { ...valueAxis, name: spec.unit, nameTextStyle: { color: color('muted') } };
      option.grid = { top: 32, bottom: 12, left: 8, right: 16, containLabel: true };
      option.series = [{ type: 'line', name: spec.name, data: spec.points, showSymbol: spec.points.length < 3, symbolSize: 7, connectNulls: false, lineStyle: { width: 2 }, emphasis: { disabled: true } }];
    } else {
      option.grid = { top: 2, bottom: 2, left: 0, right: 0 };
      option.xAxis = { type: 'value', show: false, min: 0, max: spec.values.reduce((total, item) => total + item.value, 0) || 1 };
      option.yAxis = { type: 'category', show: false, data: ['Documentos'] };
      option.tooltip = { trigger: 'item', confine: true, renderMode: 'richText', backgroundColor: color('bg'), borderColor: color('grid'), textStyle: { color: color('text') } };
      option.series = spec.values.map((item) => ({ type: 'bar', name: item.label, stack: 'status', data: [item.value], barWidth: 22, itemStyle: { color: color(item.color === 'success' ? 'brand' : item.color) }, emphasis: { disabled: true } }));
    }
    let chart: ReturnType<typeof init> | undefined;
    let disposed = false;
    const updateSize = () => {
      if (disposed || element.clientWidth <= 0 || element.clientHeight <= 0) return;
      if (!chart) {
        chart = init(element, undefined, { renderer: 'svg' });
        chart.setOption(option);
      } else chart.resize();
    };
    const resize = new ResizeObserver(updateSize);
    resize.observe(element);
    updateSize();
    return () => { disposed = true; resize.disconnect(); chart?.dispose(); };
  }, [spec, description, resolvedTheme]);
  return <div ref={host} className={styles.chart} style={spec.kind === 'status' ? { height: 28 } : undefined} />;
}
