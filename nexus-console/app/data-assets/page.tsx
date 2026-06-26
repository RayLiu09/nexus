/**
 * /data-assets — 数据资产看板.
 *
 * Editorial-atlas view of every classification the platform tracks. Boots
 * from mock data today; the eventual `/v1/data-asset-board` aggregate
 * endpoint will replace `BOARD_OVERVIEW` + `DOMAIN_CARDS` without
 * touching the presentation layer.
 *
 * Server Component on purpose — first paint streams from the server with
 * the data resolved synchronously. Interactivity (hover, animation
 * stagger) lives in `DataAssetsBoard` (a Client Component) that receives
 * the data through props.
 */
import { BOARD_OVERVIEW, DOMAIN_CARDS } from "@/lib/data-assets/mock";
import { DataAssetsBoard } from "./_components/DataAssetsBoard";

export const dynamic = "force-dynamic";

export default function DataAssetsPage() {
  return (
    <DataAssetsBoard overview={BOARD_OVERVIEW} cards={DOMAIN_CARDS} />
  );
}
