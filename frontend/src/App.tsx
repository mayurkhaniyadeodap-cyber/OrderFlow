import { ShieldOff } from "lucide-react";
import type { ReactNode } from "react";
import { createBrowserRouter, Link, Navigate, Outlet, RouterProvider, useLocation, type RouteObject } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { EmptyState, Spinner } from "./components/ui";
import { DashboardPage } from "./pages/Dashboard";
import { LoginPage } from "./pages/Login";
import { OrderPage } from "./pages/OrderPage";
import { OrdersListPage } from "./pages/OrdersList";
import { PrintView } from "./pages/PrintView";
import { UploadPage } from "./pages/UploadPO";
import { AdminActivityPage } from "./pages/admin/AdminActivity";
import { AdminContactOrdersPage } from "./pages/admin/AdminContactOrders";
import { AdminContactsPage } from "./pages/admin/AdminContacts";
import { AdminDashboardPage } from "./pages/admin/AdminDashboard";
import { AdminOrdersPage } from "./pages/admin/AdminOrders";
import { AdminSettingsPage } from "./pages/admin/AdminSettings";
import { AdminUsersPage } from "./pages/admin/AdminUsers";
import type { Role } from "./types";

function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="center-page"><Spinner /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

/** Client-side route guard (the API enforces the same rules on the server). */
function RequireRole({ roles, children, allow = true }: { roles: Role[]; children: ReactNode; allow?: boolean }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role) || !allow) {
    return (
      <div className="page">
        <EmptyState icon={<ShieldOff size={28} />} title="Not available in your panel">
          This page belongs to the {roles.map((r) => PANEL[r]).join(" / ")} panel. <Link to="/">Go to your dashboard</Link>
        </EmptyState>
      </div>
    );
  }
  return <>{children}</>;
}

const PANEL: Record<Role, string> = { admin: "Admin", sales: "Sales", printing: "Printing" };

/** "/" shows the dashboard of the signed-in role. */
function HomePage() {
  const { user } = useAuth();
  return user?.role === "admin" ? <AdminDashboardPage /> : <DashboardPage />;
}

function Root() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Outlet />
      </ToastProvider>
    </AuthProvider>
  );
}

// Client-side guards only improve navigation; every /api/admin endpoint is protected on the server.
const admin = (page: ReactNode) => <RequireRole roles={["admin"]}>{page}</RequireRole>;

export const routes: RouteObject[] = [
  {
    element: <Root />,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        element: <RequireAuth />,
        children: [
          { path: "/orders/:id/print", element: <PrintView /> },
          {
            element: <Layout />,
            children: [
              { path: "/", element: <HomePage /> },
              { path: "/orders", element: <RequireRole roles={["sales"]}><OrdersListPage mode="sales" /></RequireRole> },
              { path: "/upload", element: <RequireRole roles={["sales", "admin"]}><UploadPage /></RequireRole> },
              { path: "/queue", element: <RequireRole roles={["printing"]}><OrdersListPage mode="printing" /></RequireRole> },
              { path: "/orders/:id", element: <OrderPage /> },
              { path: "/admin/orders", element: admin(<AdminOrdersPage />) },
              { path: "/admin/users", element: admin(<AdminUsersPage />) },
              { path: "/admin/contacts", element: admin(<AdminContactsPage />) },
              { path: "/admin/contacts/:id", element: admin(<AdminContactOrdersPage />) },
              { path: "/admin/activity", element: admin(<AdminActivityPage />) },
              { path: "/admin/settings", element: admin(<AdminSettingsPage />) },
              { path: "*", element: <div className="page"><EmptyState title="Page not found"><Link to="/">Go to dashboard</Link></EmptyState></div> },
            ],
          },
        ],
      },
    ],
  },
];

const router = createBrowserRouter(routes);

export default function App() {
  return <RouterProvider router={router} />;
}
