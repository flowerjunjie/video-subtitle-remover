import { useState } from 'react'
import { Lock, Loader2 } from 'lucide-react'

interface LoginScreenProps {
  onLogin: (token: string) => void
}

export default function LoginScreen({ onLogin }: LoginScreenProps) {
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!password) return

    setLoading(true)
    setError('')

    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      const data = await res.json()

      if (data.token) {
        onLogin(data.token)
      } else {
        setError(data.error || '登录失败')
      }
    } catch {
      setError('网络错误，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white rounded-lg shadow-lg p-8 w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 bg-primary-100 rounded-full flex items-center justify-center mb-4">
            <Lock className="w-6 h-6 text-primary-600" />
          </div>
          <h1 className="text-xl font-bold text-gray-900">VSR 管理后台</h1>
          <p className="text-sm text-gray-500 mt-1">请输入管理员密码</p>
        </div>

        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="管理员密码"
            className="w-full border rounded-lg px-4 py-2 mb-4"
            disabled={loading}
            autoFocus
          />

          {error && (
            <div className="text-red-600 text-sm mb-4 text-center">{error}</div>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="w-full flex items-center justify-center gap-2 bg-primary-600 text-white rounded-lg py-2 hover:bg-primary-700 transition disabled:opacity-60"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                登录中...
              </>
            ) : (
              '登录'
            )}
          </button>
        </form>
      </div>
    </div>
  )
}