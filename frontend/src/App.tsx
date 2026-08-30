import { AuthProvider } from "@/hooks/useAuth";
import { AppRouter } from "@/app/router";

export function App() {
  return (
    <AuthProvider>
      <AppRouter />
    </AuthProvider>
  );
}
