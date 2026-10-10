import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAuth, RequireOnboarded } from "./components/ProtectedRoute";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { SetupNamePage } from "./pages/SetupNamePage";
import { HomePage } from "./pages/HomePage";
import { MachineListPage } from "./pages/MachineListPage";
import { MachineDetailPage } from "./pages/MachineDetailPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/setup-name" element={<SetupNamePage />} />
          <Route element={<RequireOnboarded />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/campuses/:campusId" element={<MachineListPage />} />
            <Route path="/machines/:machineId" element={<MachineDetailPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
