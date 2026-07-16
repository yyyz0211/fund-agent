"use client";

import { QaWorkbench } from "@/components/qa";

export default function QaPage({
  searchParams,
}: {
  searchParams: { prefill?: string };
}) {
  return <QaWorkbench prefill={searchParams.prefill} />;
}
