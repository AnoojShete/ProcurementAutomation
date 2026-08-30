import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

interface PageHeader {
  title: string;
  breadcrumb?: string;
}

interface PageHeaderContextValue extends PageHeader {
  setHeader: (header: PageHeader) => void;
}

const PageHeaderContext = createContext<PageHeaderContextValue | null>(null);

export function PageHeaderProvider({ children }: { children: ReactNode }) {
  const [header, setHeader] = useState<PageHeader>({ title: "Dashboard" });
  return <PageHeaderContext.Provider value={{ ...header, setHeader }}>{children}</PageHeaderContext.Provider>;
}

/** Consumed by AppShell's Topbar. */
export function usePageTitle(): PageHeader {
  const ctx = useContext(PageHeaderContext);
  if (!ctx) return { title: "Dashboard" };
  return { title: ctx.title, breadcrumb: ctx.breadcrumb };
}

/** Called by each page to set the topbar's title/breadcrumb for its route. */
export function usePageHeader(title: string, breadcrumb?: string) {
  const ctx = useContext(PageHeaderContext);
  useEffect(() => {
    ctx?.setHeader({ title, breadcrumb });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, breadcrumb]);
}
