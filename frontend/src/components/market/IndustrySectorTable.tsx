"use client";
import { MarketSnapshot } from "@/lib/market";
import { SectorTable } from "./SectorTable";

export function IndustrySectorTable({ snap }: { snap: MarketSnapshot }) {
  return (
    <SectorTable
      title="行业板块"
      rows={snap.industry_sectors || []}
      flows={snap.industry_flows || []}
    />
  );
}
