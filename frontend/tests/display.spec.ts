import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("状态语义、Pod身份、组件来源与证书检查", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const c = await (
    await request.post("/api/v1/cases", {
      data: { name: "Display regression" },
    })
  ).json();
  try {
    const b = await (
      await request.post(
        `/api/v1/cases/${c.id}/bundles?filename=display.tar.gz`,
        { data: readFileSync("/tmp/rancher-display-fixture.tar.gz") },
      )
    ).json();
    const base = `/api/v1/bundles/${b.id}`;
    await expect
      .poll(async () => (await (await request.get(base)).json()).state)
      .toBe("ready");
    const goto = async (name: string, params: Record<string, string> = {}) => {
      await page.goto(
        "/#" +
          new URLSearchParams({
            case: c.id,
            bundle: b.id,
            page: name,
            ...params,
          }),
      );
    };
    await goto("overview");
    const running = page.locator(".legend-row").filter({ hasText: "Running" });
    const failed = page
      .locator(".legend-row")
      .filter({ hasText: "ImagePullBackOff" });
    await expect(running.locator("i")).toHaveCSS(
      "background-color",
      "rgb(20, 155, 131)",
    );
    await expect(failed.locator("i")).toHaveCSS(
      "background-color",
      "rgb(203, 61, 75)",
    );
    await goto("pods");
    const row = (name: string) =>
      page
        .locator("tbody tr")
        .filter({ has: page.getByRole("button", { name, exact: true }) });
    await expect(row("app-notready").locator(".pill.good")).toHaveText(
      "Running",
    );
    await expect(row("app-notready").locator(".pill.warn")).toHaveText(
      "容器未全部就绪",
    );
    await expect(row("app-running").locator(".pill.warn")).toHaveCount(0);
    await expect(row("app-failed").locator(".pill.bad")).toHaveText(
      "ImagePullBackOff",
    );
    await expect(row("app-completed").locator(".pill.blue")).toHaveText(
      "Completed",
    );
    await row("app-running")
      .getByRole("button", { name: /查看日志/ })
      .click();
    await expect(
      page.locator(".log-source").first().locator("strong"),
    ).toHaveText("app-running");
    await expect(page.locator(".log-source").first()).toContainText("business");
    await expect(page.locator(".log-source").first()).toContainText(
      "未区分容器",
    );
    await expect(page.getByLabel("文件内容")).toContainText(
      "synthetic app log",
    );
    await expect(page.locator(".compact-note")).toContainText("无法拆分");
    await page.locator(".log-source").filter({ hasText: "上一次日志" }).click();
    await expect(page.getByLabel("文件内容")).toContainText(
      "previous synthetic log",
    );
    await goto("components", {
      componentGroup: "kubernetes",
      component: "kube-scheduler",
    });
    await expect(page.locator(".log-source")).toHaveCount(1);
    await expect(page.locator(".log-source")).not.toContainText("pushprox");
    await expect(page.getByLabel("文件内容")).toContainText(
      "synthetic scheduler log",
    );
    await page.getByRole("button", { name: "在 Pod 日志中查看 →" }).click();
    await expect(
      page.getByRole("heading", { name: "Pod 日志", exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("文件内容")).toContainText(
      "synthetic scheduler log",
    );
    await goto("components", {
      componentGroup: "distribution",
      component: "rke2-agent",
    });
    await expect(page.locator(".log-source")).toContainText("有效无记录");
    await goto("components", { componentGroup: "host", component: "sysstat" });
    await expect(page.getByLabel("文件内容")).toContainText("二进制");
    await goto("certificates");
    await expect(page.locator(".certificate-card")).toHaveCount(5);
    await expect(
      page.locator(".certificate-card").first().locator("strong"),
    ).toHaveText("expired.crt");
    await page.getByLabel("证书用途").selectOption("ca");
    await expect(page.locator(".certificate-card")).toHaveCount(1);
    await expect(page.locator(".certificate-card")).toContainText("CA 证书");
    await page.getByRole("button", { name: "查看原文" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByLabel("文件内容")).toContainText("Certificate:");
    await page.getByRole("button", { name: "关闭文件" }).click();
    await page.getByLabel("证书用途").selectOption("");
    await page.getByLabel("证书检查时间").selectOption("collected");
    await expect(page.getByRole("status")).toContainText("CST 不明确");
    await page.getByLabel("采集时区", { exact: true }).fill("Asia/Shanghai");
    await expect(page.getByRole("status")).toContainText(
      "2026-10-21 08:21:06 UTC",
    );
    await page.getByLabel("证书检查时间").selectOption("current");
    await page.getByLabel("搜索证书").fill("valid.crt");
    // invalid.crt also contains valid.crt; status disambiguates.
    await page.getByLabel("证书状态").selectOption("valid");
    await expect(page.locator(".certificate-card")).toHaveCount(1);
    for (const width of [1440, 1280, 1024, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await goto("certificates", { basis: "collected", zone: "Asia/Shanghai" });
      await expect(page.locator(".certificate-card")).toHaveCount(5);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `certificates @${width}`,
      ).toBe(true);
    }
    await page.screenshot({
      path: "../artifacts/certificates-synthetic.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await request.delete(`/api/v1/cases/${c.id}`);
  }
});

test("真实采集包：14份证书与核心、服务及主机日志", async ({
  page,
  request,
}) => {
  test.skip(
    !process.env.DISPLAY_ARCHIVE,
    "Requires an explicitly supplied private archive",
  );
  const c = await (
    await request.post("/api/v1/cases", {
      data: { name: "Private display acceptance" },
    })
  ).json();
  try {
    const b = await (
      await request.post(
        `/api/v1/cases/${c.id}/bundles?filename=private.tar.gz`,
        { data: readFileSync(process.env.DISPLAY_ARCHIVE!) },
      )
    ).json();
    const base = `/api/v1/bundles/${b.id}`;
    await expect
      .poll(async () => (await (await request.get(base)).json()).state, {
        timeout: 60000,
      })
      .toBe("ready");
    const overview = await (await request.get(base + "/overview")).json();
    expect(overview.counts).toMatchObject({
      files: 324,
      pods: 76,
      nodes: 3,
      namespaces: 14,
    });
    const certs = await (await request.get(base + "/certificates")).json();
    expect(certs.total).toBe(14);
    expect(certs.counts.unknown).toBe(0);
    const core = await (
      await request.get(
        base + "/catalog/componentLogs?component_group=kubernetes&limit=200",
      )
    ).json();
    for (const name of [
      "kube-apiserver",
      "kube-controller-manager",
      "kube-scheduler",
      "cloud-controller-manager",
      "kubelet",
    ]) {
      expect(
        core.items.some((l: any) => l.component === name),
        name,
      ).toBe(true);
    }
    expect(core.items.some((l: any) => l.path.includes("pushprox"))).toBe(
      false,
    );
    const all = await (
      await request.get(base + "/catalog/componentLogs?limit=200")
    ).json();
    expect(all.items.some((l: any) => l.component === "containerd")).toBe(true);
    expect(all.items.some((l: any) => l.path === "journald/rke2-server")).toBe(
      true,
    );
    expect(all.items.some((l: any) => l.path === "systemlogs/syslog")).toBe(
      true,
    );
    const goto = (name: string, params: Record<string, string> = {}) =>
      page.goto(
        "/#" +
          new URLSearchParams({
            case: c.id,
            bundle: b.id,
            page: name,
            ...params,
          }),
      );
    await goto("certificates");
    await expect(page.locator(".certificate-card")).toHaveCount(14);
    await page.getByLabel("证书用途").selectOption("ca");
    await expect(page.locator(".certificate-card")).toHaveCount(2);
    await goto("components", {
      componentGroup: "runtime",
      component: "containerd",
    });
    await expect(page.locator(".log-source")).toHaveCount(2);
    await expect(
      page.locator(".log-source").filter({ hasText: "journald/containerd" }),
    ).toBeVisible();
    await expect(
      page.locator(".log-source").filter({ hasText: "rke2/containerd.log" }),
    ).toBeVisible();
    await page
      .locator(".log-source")
      .filter({ hasText: "rke2/containerd.log" })
      .click();
    await expect(page.locator(".log-line").first()).toBeVisible();
    await page
      .getByLabel("日志关键字")
      .fill("unlikely-keyword-display-acceptance-123456");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.getByLabel("文件内容")).toContainText("未找到匹配");
    await goto("components", {
      componentGroup: "distribution",
      component: "rke2-agent",
    });
    await expect(page.locator(".log-source")).toContainText("有效无记录");
    await goto("certificates");
    await page.screenshot({
      path: "../artifacts/certificates-private.png",
      fullPage: true,
    });
  } finally {
    await request.delete(`/api/v1/cases/${c.id}`);
  }
});
