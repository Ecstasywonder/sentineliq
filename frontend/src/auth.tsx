import { createContext, useContext, useEffect, useState, type PropsWithChildren } from 'react'
import {
  clearSession,
  getCurrentUser,
  hasSession,
  login,
  onSessionCleared,
  type User,
} from './api'

type AuthState = {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthState | undefined>(undefined)

export function AuthProvider({ children }: PropsWithChildren): React.JSX.Element {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(hasSession())

  useEffect(() => {
    let active = true
    const unsubscribe = onSessionCleared(() => {
      if (active) setUser(null)
    })

    if (hasSession()) {
      void getCurrentUser()
        .then((currentUser) => {
          if (active) setUser(currentUser)
        })
        .catch(() => clearSession())
        .finally(() => {
          if (active) setLoading(false)
        })
    }

    return () => {
      active = false
      unsubscribe()
    }
  }, [])

  const signIn = async (email: string, password: string) => {
    setUser(await login(email, password))
  }

  const signOut = () => {
    clearSession()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext)
  if (!state) throw new Error('useAuth must be used inside AuthProvider')
  return state
}
