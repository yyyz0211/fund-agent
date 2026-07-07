"use client";
import { MarketSnapshot } from "@/lib/market";
import { SectorTable } from "./SectorTable";

export function ConceptSectorTable({ snap }: { snap: MarketSnapshot }) {
  return (
    <SectorTable
      title="概念板块"
      rows={snap.concept_sectors || []}
      flows={snap.concept_flows || []}
    />
  );
}
