import { useEffect, useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router";

import { makeQueryClient } from "@/api/queryClient";
import { Toaster } from "@/components/ui/toaster";
import { createAppRouter, preloadRoutes } from "@/router";

export default function App() {
  const [queryClient] = useState(makeQueryClient);
  const [router] = useState(createAppRouter);
  // Every page's chunk, in idle time after the first render (router.tsx).
  useEffect(preloadRoutes, []);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>
  );
}
