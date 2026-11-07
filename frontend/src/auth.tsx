import {
  createContext,
  useContext,
  useEffect,
  useState,
  type PropsWithChildren,
} from "react";
import {
  clearSessionIfCurrent,
  currentSession,
  getCurrentUser,
  hasSession,
  login,
  logout,
  onSessionCleared,
  type User,
} from "./api";

type AuthState = {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({
  children,
}: PropsWithChildren): React.JSX.Element {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(hasSession());

  useEffect(() => {
    const sessionAtLoad = currentSession();
    const unsubscribe = onSessionCleared(() => setUser(null));

    if (sessionAtLoad) {
      getCurrentUser()
        .then(setUser)
        .catch(() => clearSessionIfCurrent(sessionAtLoad))
        .finally(() => setLoading(false));
    }

    return unsubscribe;
  }, []);

  const signIn = async (email: string, password: string) => {
    const next = await login(email, password);
    setUser(next);
    setLoading(false);
  };

  const signOut = () => {
    logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (!state) throw new Error("useAuth must be used inside AuthProvider");
  return state;
}
