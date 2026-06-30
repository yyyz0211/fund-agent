import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface MetricItem {
  label: string;
  value: string;
  sub?: string;
}

export function MetricCards({ items }: { items: MetricItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((m) => (
        <Card key={m.label} className="p-5">
          <CardHeader className="mb-4">
            <CardTitle>{m.label}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tracking-tight text-gray-950">{m.value}</div>
            {m.sub && <div className="mt-2 text-xs text-gray-500">{m.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
