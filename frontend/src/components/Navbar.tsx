"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getCurrentUser, clearAuthToken } from "@/lib/api";
import { Shield, Activity, FileText, BookOpen, Monitor, LogOut, PlusCircle, MessageSquare } from "lucide-react";

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    setUser(getCurrentUser());
  }, [pathname]);

  const handleLogout = () => {
    clearAuthToken();
    setUser(null);
    router.push("/login");
  };

  const navItems = [
    { name: "Dashboard", href: "/dashboard", icon: Activity },
    { name: "Incidents", href: "/incidents", icon: FileText },
    { name: "AI Chatbot", href: "/chat", icon: MessageSquare },
    { name: "Knowledge Base", href: "/knowledge", icon: BookOpen },
    { name: "Endpoints", href: "/agents", icon: Monitor },
  ];

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-sm">
      <div className="max-w-7xl mx-auto px-3 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-3">
          <div className="flex items-center gap-4 lg:gap-6 min-w-0">
            <Link
              href="/dashboard"
              className="flex items-center gap-2 text-slate-900 font-bold text-lg tracking-tight whitespace-nowrap shrink-0"
            >
              <div className="w-8 h-8 rounded-lg bg-sky-600 flex items-center justify-center text-white shadow-sm shrink-0">
                <Shield className="w-5 h-5" />
              </div>
              <span className="whitespace-nowrap">
                AISD <span className="text-sky-600 text-sm font-semibold">Incident AI</span>
              </span>
            </Link>

            <nav className="hidden lg:flex items-center space-x-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    className={`inline-flex items-center px-3 py-1.5 rounded-md text-sm font-medium transition-colors whitespace-nowrap shrink-0 ${
                      active
                        ? "bg-sky-50 text-sky-700"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                    }`}
                  >
                    <Icon className="w-4 h-4 mr-1.5 shrink-0" />
                    <span>{item.name}</span>
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <Link
              href="/incidents/new"
              className="inline-flex items-center px-3 py-1.5 border border-transparent text-xs sm:text-sm font-medium rounded-md shadow-sm text-white bg-sky-600 hover:bg-sky-700 transition whitespace-nowrap shrink-0"
            >
              <PlusCircle className="w-4 h-4 mr-1.5 shrink-0" />
              <span>Report Incident</span>
            </Link>

            {user ? (
              <div className="flex items-center gap-2 sm:gap-3 border-l border-slate-200 pl-2 sm:pl-4 shrink-0">
                <div className="text-right min-w-0">
                  <div className="text-xs font-semibold text-slate-800 whitespace-nowrap truncate max-w-[130px] sm:max-w-[190px]">
                    {user.name}
                  </div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-sky-600 bg-sky-50 px-1.5 py-0.5 rounded inline-block whitespace-nowrap">
                    {user.role}
                  </div>
                </div>
                <button
                  onClick={handleLogout}
                  title="Logout"
                  aria-label="Logout"
                  className="p-1.5 text-slate-400 hover:text-rose-600 transition shrink-0"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <Link
                href="/login"
                className="text-sm font-medium text-slate-600 hover:text-slate-900 transition whitespace-nowrap shrink-0"
              >
                Sign In
              </Link>
            )}
          </div>
        </div>

        {/* Compact Navigation Bar for Split-Screen / Mobile / Tablet (< lg) */}
        <nav className="flex lg:hidden items-center gap-1.5 pb-2.5 pt-1 border-t border-slate-100 overflow-x-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.name}
                href={item.href}
                className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium transition-colors whitespace-nowrap shrink-0 ${
                  active
                    ? "bg-sky-50 text-sky-700 border border-sky-100"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                }`}
              >
                <Icon className="w-3.5 h-3.5 mr-1.5 shrink-0" />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
