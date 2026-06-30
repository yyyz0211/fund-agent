import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface MetricItem {
  label: string;
  value: string;
  sub?: string;
}

export function MetricCards({ items }: { items: MetricItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      {items.map((m) => (
        <Card key={m.label}>
          <CardHeader><CardTitle>{m.label}</CardTitle></CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{m.value}</div>
            {m.sub && <div className="text-xs text-gray-500">{m.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
