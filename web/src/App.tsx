import { useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';

interface Forecast {
  id: string;
  plot_id: string;
  days: string[];
  p10_t_ha: number[];
  p50_t_ha: number[];
  p90_t_ha: number[];
  probability_target: number;
  target_t_ha: number;
  diagnostics: Record<string, number>;
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export default function App() {
  const [plotId, setPlotId] = useState('greenhouse-3');
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/v1/plots/${plotId}/latest`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setForecast((await response.json()) as Forecast);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  const option = useMemo(() => {
    if (!forecast) return {};
    const toSeries = (values: number[]) =>
      forecast.days.map((day, i) => [day, Number(values[i]?.toFixed(2))]);
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { data: ['P90', 'P50', 'P10'], textStyle: { color: '#cbd5e1' } },
      grid: { left: 50, right: 20, top: 40, bottom: 40 },
      xAxis: { type: 'category', data: forecast.days, axisLabel: { color: '#94a3b8' } },
      yAxis: {
        type: 'value',
        name: 'т/га',
        nameTextStyle: { color: '#94a3b8' },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#1e293b' } },
      },
      series: [
        {
          name: 'P90',
          type: 'line',
          data: toSeries(forecast.p90_t_ha),
          showSymbol: false,
          lineStyle: { opacity: 0.35 },
          areaStyle: { color: 'rgba(34,197,94,0.12)' },
          itemStyle: { color: '#4ade80' },
        },
        {
          name: 'P50',
          type: 'line',
          data: toSeries(forecast.p50_t_ha),
          showSymbol: false,
          lineStyle: { width: 3 },
          itemStyle: { color: '#22c55e' },
        },
        {
          name: 'P10',
          type: 'line',
          data: toSeries(forecast.p10_t_ha),
          showSymbol: false,
          lineStyle: { opacity: 0.35 },
          itemStyle: { color: '#16a34a' },
        },
      ],
    };
  }, [forecast]);

  return (
    <main style={{ maxWidth: 980, margin: '40px auto', fontFamily: 'system-ui', color: '#e2e8f0' }}>
      <h1>АгроПрогноз</h1>
      <p style={{ color: '#94a3b8' }}>
        Вероятностный прогноз урожая: P10 / P50 / P90 и вероятность достижения цели
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          value={plotId}
          onChange={(e) => setPlotId(e.target.value)}
          style={{ padding: 10, borderRadius: 8, border: '1px solid #334155', background: '#0f172a', color: '#e2e8f0' }}
        />
        <button onClick={load} disabled={loading} style={{ padding: '10px 18px', borderRadius: 8, border: 0, background: '#22c55e', color: '#052e16', fontWeight: 700 }}>
          {loading ? 'Загрузка…' : 'Загрузить прогноз'}
        </button>
      </div>

      {error && <p style={{ color: '#f87171' }}>Ошибка: {error}</p>}

      {forecast && (
        <>
          <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
            <div style={{ flex: 1, padding: 16, background: '#1e293b', borderRadius: 12 }}>
              <div style={{ color: '#94a3b8', fontSize: 12 }}>Вероятность цели {forecast.target_t_ha} т/га</div>
              <div style={{ fontSize: 32, fontWeight: 700, color: '#4ade80' }}>
                {(forecast.probability_target * 100).toFixed(1)} %
              </div>
            </div>
            <div style={{ flex: 1, padding: 16, background: '#1e293b', borderRadius: 12 }}>
              <div style={{ color: '#94a3b8', fontSize: 12 }}>Прогноз на конец периода (P50)</div>
              <div style={{ fontSize: 32, fontWeight: 700 }}>
                {forecast.p50_t_ha.at(-1)?.toFixed(1)} т/га
              </div>
            </div>
          </div>

          <div style={{ background: '#0f172a', borderRadius: 12, padding: 12 }}>
            <ReactECharts option={option} style={{ height: 420 }} />
          </div>

          <h3>Почему такой прогноз?</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
            {Object.entries(forecast.diagnostics).map(([key, value]) => (
              <div key={key} style={{ background: '#1e293b', borderRadius: 10, padding: 12 }}>
                <div style={{ color: '#94a3b8', fontSize: 12 }}>{key}</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{(value * 100).toFixed(0)} %</div>
                <div style={{ height: 6, background: '#334155', borderRadius: 4, marginTop: 6 }}>
                  <div style={{ width: `${value * 100}%`, height: '100%', background: value > 0.66 ? '#22c55e' : value > 0.33 ? '#eab308' : '#ef4444', borderRadius: 4 }} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
