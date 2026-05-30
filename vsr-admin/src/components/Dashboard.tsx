import { RefreshCw } from 'lucide-react'
import clsx from 'clsx'

interface Stats {
  total: number
  unused: number
  active: number
  expired: number
  total_revenue: number
}

interface DashboardProps {
  stats: Stats
  onRefresh: () => void
}

function StatCard({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div className="bg-white rounded-lg shadow p-4 flex flex-col items-center">
      <span className={clsx('text-3xl font-bold', color)}>{value}</span>
      <span className="text-gray-500 text-sm mt-1">{label}</span>
    </div>
  )
}

export default function Dashboard({ stats, onRefresh }: DashboardProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      <StatCard label="总生成数" value={stats.total} color="text-gray-800" />
      <StatCard label="未使用" value={stats.unused} color="text-green-600" />
      <StatCard label="使用中" value={stats.active} color="text-blue-600" />
      <StatCard label="已过期" value={stats.expired} color="text-gray-500" />
      <StatCard label="总收益" value={`¥${stats.total_revenue}`} color="text-primary-600" />
      <button
        onClick={onRefresh}
        className="col-span-2 md:col-span-5 flex items-center justify-center gap-2 bg-primary-600 text-white rounded-lg shadow py-2 hover:bg-primary-700 transition"
      >
        <RefreshCw className="w-4 h-4" />
        刷新统计
      </button>
    </div>
  )
}