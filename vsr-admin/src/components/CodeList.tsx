import { Trash2, ChevronLeft, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

interface Code {
  code: string
  months: number
  price: number
  created_at: string
  activated_at: string | null
  expires_at: string | null
  machine_id: string | null
  status: 'unused' | 'active' | 'expired'
}

interface CodeListProps {
  codes: Code[]
  loading: boolean
  filter: string
  page: number
  totalPages: number
  onFilterChange: (f: string) => void
  onPageChange: (p: number) => void
  onDelete: (code: string) => void
}

const STATUS_MAP = {
  unused: { label: '未使用', color: 'bg-green-100 text-green-800' },
  active: { label: '使用中', color: 'bg-blue-100 text-blue-800' },
  expired: { label: '已过期', color: 'bg-gray-100 text-gray-500' },
}

const FILTER_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'unused', label: '未使用' },
  { value: 'active', label: '使用中' },
  { value: 'expired', label: '已过期' },
]

export default function CodeList({
  codes,
  loading,
  filter,
  page,
  totalPages,
  onFilterChange,
  onPageChange,
  onDelete,
}: CodeListProps) {
  return (
    <div className="bg-white rounded-lg shadow">
      <div className="p-4 border-b flex items-center gap-4">
        <span className="text-gray-600">筛选</span>
        <select
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          className="border rounded px-3 py-1.5"
        >
          {FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="p-8 text-center text-gray-500">加载中...</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left text-sm font-medium text-gray-600">序号</th>
                <th className="px-4 py-2 text-left text-sm font-medium text-gray-600">激活码</th>
                <th className="px-4 py-2 text-center text-sm font-medium text-gray-600">月数</th>
                <th className="px-4 py-2 text-center text-sm font-medium text-gray-600">价格</th>
                <th className="px-4 py-2 text-center text-sm font-medium text-gray-600">状态</th>
                <th className="px-4 py-2 text-center text-sm font-medium text-gray-600">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {codes.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-500">暂无数据</td>
                </tr>
              ) : (
                codes.map((code, idx) => {
                  const statusInfo = STATUS_MAP[code.status] || STATUS_MAP.expired
                  return (
                    <tr key={code.code} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-sm text-gray-600">{(page - 1) * 20 + idx + 1}</td>
                      <td className="px-4 py-2 text-sm font-mono">{code.code}</td>
                      <td className="px-4 py-2 text-sm text-center">{code.months}</td>
                      <td className="px-4 py-2 text-sm text-center">¥{code.price.toFixed(1)}</td>
                      <td className="px-4 py-2 text-center">
                        <span className={clsx('px-2 py-0.5 rounded-full text-xs', statusInfo.color)}>
                          {statusInfo.label}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-center">
                        <button
                          onClick={() => onDelete(code.code)}
                          className="inline-flex items-center gap-1 text-red-600 hover:text-red-800"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="p-4 border-t flex items-center justify-center gap-4">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded border hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="w-4 h-4" />
          上一页
        </button>
        <span className="text-sm text-gray-600">
          第 {page} / {totalPages} 页
        </span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded border hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          下一页
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}