import { useState, useEffect, useCallback } from 'react'
import { X, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import clsx from 'clsx'

export type ToastType = 'success' | 'error' | 'info'

interface Toast {
  id: number
  message: string
  type: ToastType
}

let toastId = 0
let addToastFn: ((message: string, type: ToastType) => void) | null = null

export function showToast(message: string, type: ToastType = 'info') {
  addToastFn?.(message, type)
}

export default function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  useEffect(() => {
    addToastFn = (message: string, type: ToastType) => {
      const id = ++toastId
      setToasts((prev) => [...prev, { id, message, type }])
      setTimeout(() => removeToast(id), 3000)
    }
    return () => {
      addToastFn = null
    }
  }, [removeToast])

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={clsx(
            'pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg text-white min-w-72 max-w-md',
            'animate-in slide-in-from-right duration-300',
            toast.type === 'success' && 'bg-green-600',
            toast.type === 'error' && 'bg-red-600',
            toast.type === 'info' && 'bg-blue-600',
          )}
        >
          {toast.type === 'success' && <CheckCircle className="w-5 h-5 shrink-0" />}
          {toast.type === 'error' && <AlertCircle className="w-5 h-5 shrink-0" />}
          {toast.type === 'info' && <Loader2 className="w-5 h-5 shrink-0 animate-spin" />}
          <span className="text-sm font-medium flex-1">{toast.message}</span>
          <button
            onClick={() => removeToast(toast.id)}
            className="shrink-0 hover:opacity-80"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  )
}