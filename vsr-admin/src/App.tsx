import { useState, useEffect, useCallback } from 'react'
import Dashboard from './components/Dashboard'
import CodeList from './components/CodeList'
import CodeGenerator from './components/CodeGenerator'
import ToastContainer, { showToast } from './components/Toast'
import LoginScreen from './components/LoginScreen'

const API_BASE = '/api'

interface Stats {
  total: number
  unused: number
  active: number
  expired: number
  total_revenue: number
}

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

interface PageData {
  codes: Code[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

const TOKEN_KEY = 'vsr_admin_token'

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem(TOKEN_KEY))
  const [stats, setStats] = useState<Stats>({ total: 0, unused: 0, active: 0, expired: 0, total_revenue: 0 })
  const [codes, setCodes] = useState<Code[]>([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)

  const fetchStats = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/stats`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (res.status === 401) {
        setToken(null)
        localStorage.removeItem(TOKEN_KEY)
        return
      }
      const data = await res.json()
      setStats(data)
    } catch (e) {
      console.error('Failed to fetch stats', e)
    }
  }, [token])

  const fetchCodes = useCallback(async (p: number, f: string) => {
    if (!token) return
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/codes?page=${p}&page_size=20&status=${f}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (res.status === 401) {
        setToken(null)
        localStorage.removeItem(TOKEN_KEY)
        return
      }
      const data: PageData = await res.json()
      setCodes(data.codes)
      setTotalPages(data.total_pages)
      setPage(data.page)
    } catch (e) {
      console.error('Failed to fetch codes', e)
    } finally {
      setLoading(false)
    }
  }, [token])

  const deleteCode = useCallback(async (code: string) => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/codes/${code}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      })
      const data = await res.json()
      if (data.success) {
        showToast(`激活码 ${code} 已删除`, 'success')
        await fetchStats()
        await fetchCodes(page, filter)
      } else {
        showToast(data.message || '删除失败', 'error')
      }
    } catch (e) {
      showToast('删除失败', 'error')
    }
  }, [token, page, filter, fetchStats, fetchCodes])

  const generateCodes = useCallback(async (count: number, months: number) => {
    if (!token) return
    setGenerating(true)
    try {
      const res = await fetch(`${API_BASE}/codes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ count, months }),
      })
      const data = await res.json()
      if (data.success) {
        showToast(`成功生成 ${data.count} 个激活码`, 'success')
        await fetchStats()
        await fetchCodes(1, 'all')
      } else {
        showToast(data.message || '生成失败', 'error')
      }
    } catch (e) {
      showToast('生成失败', 'error')
    } finally {
      setGenerating(false)
    }
  }, [token, fetchStats, fetchCodes])

  useEffect(() => {
    if (token) {
      fetchStats()
      fetchCodes(1, 'all')
    }
  }, [token, fetchStats, fetchCodes])

  const handleLogin = (newToken: string) => {
    localStorage.setItem(TOKEN_KEY, newToken)
    setToken(newToken)
  }

  const handleFilterChange = (f: string) => {
    setFilter(f)
    fetchCodes(1, f)
  }

  if (!token) {
    return <LoginScreen onLogin={handleLogin} />
  }

  return (
    <div className="min-h-screen bg-gray-100">
      <ToastContainer />
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto py-4 px-4 sm:px-6 lg:px-8 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-900">VSR 激活码管理后台</h1>
          <button
            onClick={() => {
              setToken(null)
              localStorage.removeItem(TOKEN_KEY)
            }}
            className="text-sm text-gray-500 hover:text-gray-800"
          >
            退出登录
          </button>
        </div>
      </header>
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <Dashboard stats={stats} onRefresh={fetchStats} />
        <div className="mt-6">
          <CodeGenerator onGenerate={generateCodes} loading={generating} />
        </div>
        <div className="mt-6">
          <CodeList
            codes={codes}
            loading={loading}
            filter={filter}
            page={page}
            totalPages={totalPages}
            onFilterChange={handleFilterChange}
            onPageChange={(p) => fetchCodes(p, filter)}
            onDelete={deleteCode}
          />
        </div>
      </main>
    </div>
  )
}

export default App