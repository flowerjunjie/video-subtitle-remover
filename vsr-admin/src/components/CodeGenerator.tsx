import { useState } from 'react'
import { Plus, Loader2 } from 'lucide-react'

const PRICE_PER_MONTH = 9.9

const MONTH_OPTIONS = [
  { label: `1个月 (¥${(PRICE_PER_MONTH * 1).toFixed(1)})`, value: 1 },
  { label: `3个月 (¥${(PRICE_PER_MONTH * 3).toFixed(1)})`, value: 3 },
  { label: `6个月 (¥${(PRICE_PER_MONTH * 6).toFixed(1)})`, value: 6 },
  { label: `12个月 (¥${(PRICE_PER_MONTH * 12).toFixed(1)})`, value: 12 },
]

interface CodeGeneratorProps {
  onGenerate: (count: number, months: number) => void
  loading?: boolean
}

export default function CodeGenerator({ onGenerate, loading = false }: CodeGeneratorProps) {
  const [count, setCount] = useState(1)
  const [months, setMonths] = useState(1)

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h2 className="text-lg font-semibold mb-4">生成激活码</h2>
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <label className="block text-sm text-gray-600 mb-1">生成数量</label>
          <input
            type="number"
            min={1}
            max={100}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
            className="w-24 border rounded px-3 py-1.5"
          />
        </div>
        <div>
          <label className="block text-sm text-gray-600 mb-1">月数</label>
          <select
            value={months}
            onChange={(e) => setMonths(parseInt(e.target.value))}
            className="border rounded px-3 py-1.5"
          >
            {MONTH_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div className="text-sm text-gray-500 pb-1">¥{PRICE_PER_MONTH}/月 起</div>
        <button
          onClick={() => onGenerate(count, months)}
          disabled={loading}
          className="flex items-center gap-2 bg-primary-600 text-white rounded px-4 py-1.5 hover:bg-primary-700 transition disabled:opacity-60 disabled:cursor-wait"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              生成中...
            </>
          ) : (
            <>
              <Plus className="w-4 h-4" />
              生成
            </>
          )}
        </button>
      </div>
    </div>
  )
}