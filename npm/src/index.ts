/**
 * QWED-Finance TypeScript SDK
 *
 * Bridges to the Python qwed-finance package for Node.js environments.
 *
 * SECURITY MODEL (Boundary-1: every argument crossing this API is
 * untrusted — Express query strings, LLM numeric strings, CSV text):
 *
 * - TypeScript types are compile-time only. Every public method validates
 *   its inputs at runtime before use (CWE-843).
 * - Caller data NEVER enters executed Python source. All bridge scripts
 *   below are static constants; payloads travel as JSON over the child's
 *   stdin pipe, never the command line — hostile values (quotes,
 *   backslashes, newlines, Python conditional-expression fragments)
 *   cannot break out of a literal (CWE-94), and no caller payload is
 *   observable in process listings (CWE-200). See #58, #59.
 * - Bridge output is parsed defensively: the first JSON-object line wins,
 *   its shape is validated, and any deviation (empty output, unparseable
 *   output, wrong shape) rejects instead of resolving a default verdict.
 *   There are no fail-open fallbacks on the error path.
 *
 * @example
 * ```typescript
 * import { FinanceVerifier, ComplianceGuard } from '@qwed-ai/finance';
 *
 * const verifier = new FinanceVerifier();
 * const result = await verifier.verifyNPV([-1000, 300, 400], 0.1, "$180");
 * console.log(result.verified);
 * ```
 */

import { PythonShell } from 'python-shell';

export interface VerificationResult {
    verified: boolean;
    computed_value?: string;
    violations?: string[];
    receipt_id?: string;
    input_hash?: string;
    timestamp?: string;
}

export interface AMLResult {
    needs_flagging: boolean;
    reason: string;
    verified: boolean;
}

export interface PaymentVerificationResult {
    can_proceed: boolean;
    status: 'approved' | 'blocked' | 'pending_review';
    violations: string[];
    receipt_ids: string[];
}

// ---------------------------------------------------------------------------
// Runtime input validation (TypeScript annotations are erased at runtime)
// ---------------------------------------------------------------------------

/** Upper bound on the serialized stdin payload, measured in UTF-8 bytes. */
const MAX_BRIDGE_PAYLOAD_BYTES = 65536;

/** Upper bound on captured bridge stdout (verdict envelopes are tiny). */
const MAX_BRIDGE_STDOUT_BYTES = 1048576;

/** Wall-clock bound per bridge invocation. */
const BRIDGE_TIMEOUT_MS = 60000;

/** ISO 3166-1 alpha-2 shape, enforced after trim + case normalization. */
const COUNTRY_CODE_PATTERN = /^[A-Z]{2}$/;

/**
 * Officially-assigned ISO 3166-1 alpha-2 set. Shape validation alone
 * admits nonexistent jurisdictions (ZZ, AA) that the AML rule then
 * treats as cleared — fail closed on unassigned codes instead.
 */
const ISO_ALPHA_2 = new Set([
    'AF', 'AX', 'AL', 'DZ', 'AS', 'AD', 'AO', 'AI', 'AQ', 'AG', 'AR', 'AM',
    'AW', 'AU', 'AT', 'AZ', 'BS', 'BH', 'BD', 'BB', 'BY', 'BE', 'BZ', 'BJ',
    'BM', 'BT', 'BO', 'BQ', 'BA', 'BW', 'BV', 'BR', 'IO', 'BN', 'BG', 'BF',
    'BI', 'KH', 'CM', 'CA', 'KY', 'CF', 'TD', 'CL', 'CN', 'CX', 'CC', 'CO',
    'KM', 'CG', 'CD', 'CK', 'CR', 'CI', 'HR', 'CU', 'CV', 'CW', 'CY', 'CZ', 'DK',
    'DJ', 'DM', 'DO', 'EC', 'EG', 'SV', 'GQ', 'ER', 'EE', 'ET', 'FK',
    'FO', 'FJ', 'FI', 'FR', 'GF', 'PF', 'TF', 'GA', 'GM', 'GE', 'DE', 'GH',
    'GI', 'GR', 'GL', 'GD', 'GP', 'GU', 'GT', 'GG', 'GN', 'GW', 'GY', 'HT',
    'HM', 'VA', 'HN', 'HK', 'HU', 'IS', 'IN', 'ID', 'IR', 'IQ', 'IE', 'IM',
    'IL', 'IT', 'JM', 'JP', 'JE', 'JO', 'KZ', 'KE', 'KI', 'KP', 'KR', 'KW',
    'KG', 'LA', 'LV', 'LB', 'LS', 'LR', 'LY', 'LI', 'LT', 'LU', 'MO', 'MG',
    'MW', 'MY', 'MV', 'ML', 'MT', 'MH', 'MQ', 'MR', 'MU', 'YT', 'MX', 'FM',
    'MD', 'MC', 'MN', 'ME', 'MS', 'MA', 'MZ', 'MM', 'NA', 'NR', 'NP', 'NL',
    'NC', 'NZ', 'NI', 'NE', 'NG', 'NU', 'NF', 'MK', 'MP', 'NO', 'OM', 'PK',
    'PW', 'PS', 'PA', 'PG', 'PY', 'PE', 'PH', 'PN', 'PL', 'PT', 'PR', 'QA',
    'RE', 'RO', 'RU', 'RW', 'BL', 'SH', 'KN', 'LC', 'MF', 'PM', 'VC', 'WS',
    'SM', 'ST', 'SA', 'SN', 'RS', 'SG', 'SX', 'SK', 'SI', 'SB', 'SC', 'SO', 'ZA',
    'GS', 'SS', 'ES', 'LK', 'SD', 'SL', 'SR', 'SJ', 'SZ', 'SE', 'CH', 'SY', 'TW',
    'TJ', 'TZ', 'TH', 'TL', 'TG', 'TK', 'TO', 'TT', 'TN', 'TR', 'TM', 'TC',
    'TV', 'UG', 'UA', 'AE', 'GB', 'US', 'UM', 'UY', 'UZ', 'VU', 'VE', 'VN',
    'VG', 'VI', 'WF', 'EH', 'YE', 'ZM', 'ZW',
]);

/** Reject anything that is not a finite JS number (strings, NaN, ±Infinity). */
function assertFiniteNumber(value: unknown, name: string): number {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new TypeError(
            `${name} must be a finite number, got: ${typeof value}`
        );
    }
    return value;
}

function assertNonEmptyString(value: unknown, name: string, maxLength: number): string {
    if (typeof value !== 'string' || value.length === 0 || value.length > maxLength) {
        throw new TypeError(
            `${name} must be a non-empty string of at most ${maxLength} characters`
        );
    }
    return value;
}

/** ISO country code: strings only, normalized to uppercase `AA` form. */
function assertCountryCode(value: unknown): string {
    if (typeof value !== 'string') {
        throw new TypeError(
            `countryCode must be a string, got: ${typeof value}`
        );
    }
    const normalized = value.trim().toUpperCase();
    if (!COUNTRY_CODE_PATTERN.test(normalized) || !ISO_ALPHA_2.has(normalized)) {
        throw new RangeError(
            'countryCode must be an assigned ISO 3166-1 alpha-2 code (two letters)'
        );
    }
    return normalized;
}

// ---------------------------------------------------------------------------
// Static bridge scripts (ZERO interpolation — never embed caller data here)
// ---------------------------------------------------------------------------

const VERIFY_NPV_SCRIPT = [
    'import json, sys',
    'from qwed_finance import FinanceVerifier',
    'payload = json.load(sys.stdin)',
    'result = FinanceVerifier().verify_npv(',
    '    payload["cashflows"], payload["rate"], payload["llm_output"])',
    'print(json.dumps({',
    '    "verified": result.verified,',
    '    "computed_value": result.computed_value,',
    '}))',
].join('\n');

const VERIFY_LOAN_SCRIPT = [
    'import json, sys',
    'from qwed_finance import OpenResponsesIntegration',
    'payload = json.load(sys.stdin)',
    'qwed = OpenResponsesIntegration()',
    'result = qwed.handle_tool_call("calculate_loan_payment", {',
    '    "principal": payload["principal"],',
    '    "annual_rate": payload["annual_rate"],',
    '    "months": payload["months"],',
    '})',
    'print(json.dumps({',
    '    "verified": result.receipt.verified if result.receipt else False,',
    '    "computed_value": result.result.get("monthly_payment") if result.result else None,',
    '    "receipt_id": result.receipt.receipt_id if result.receipt else None',
    '}))',
].join('\n');

const CHECK_AML_SCRIPT = [
    'import json, sys',
    'from qwed_finance import OpenResponsesIntegration',
    'payload = json.load(sys.stdin)',
    'qwed = OpenResponsesIntegration()',
    'result = qwed.handle_tool_call("check_aml_compliance", {',
    '    "amount": payload["amount"],',
    '    "country_code": payload["country_code"],',
    '})',
    'print(json.dumps(result.result))',
].join('\n');

const VERIFY_TOKEN_SCRIPT = [
    'import json, sys',
    'from qwed_finance import UCPIntegration',
    'payload = json.load(sys.stdin)',
    'ucp = UCPIntegration()',
    'result = ucp.verify_payment_token(payload["token"])',
    'print(json.dumps({',
    '    "can_proceed": result.can_proceed,',
    '    "status": result.status.value,',
    '    "violations": result.violations,',
    '    "receipt_ids": [r.receipt_id for r in result.receipts]',
    '}))',
].join('\n');

// ---------------------------------------------------------------------------
// Fail-closed bridge execution and output parsing
// ---------------------------------------------------------------------------

/** First stdout line that parses as a JSON object; null when absent. */
function firstJsonObject(lines: string[] | undefined): Record<string, unknown> | null {
    if (!lines) {
        return null;
    }
    for (const line of lines) {
        try {
            const value: unknown = JSON.parse(line);
            if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
                return value as Record<string, unknown>;
            }
            // Non-object JSON line: not a verdict envelope, keep scanning.
        } catch {
            // Non-JSON line (warnings, logging): keep scanning for the verdict.
        }
    }
    return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Execute a static bridge script, feeding the payload as JSON over the
 * child's stdin pipe (python-shell `.send()`). Argv carries only the
 * static script, so no caller-controlled value ever appears in the
 * process command line (CWE-200) or counts against OS command-line
 * limits. stderr is drained by the transport library, so a chatty child
 * cannot deadlock the pipe. stdout and runtime are bounded, and every
 * failure mode rejects (fail closed).
 */
function runBridgeScript(
    pythonPath: string,
    script: string,
    payload: Record<string, unknown>
): Promise<string[]> {
    const input = JSON.stringify(payload);
    if (Buffer.byteLength(input, 'utf8') > MAX_BRIDGE_PAYLOAD_BYTES) {
        return Promise.reject(
            new RangeError('Bridge payload exceeds the transport limit')
        );
    }
    return new Promise((resolve, reject) => {
        let settled = false;
        const settle = (finish: () => void): void => {
            if (!settled) {
                settled = true;
                clearTimeout(timer);
                finish();
            }
        };
        let shell: PythonShell;
        try {
            shell = new PythonShell(script, {
                mode: 'text',
                pythonPath,
                pythonOptions: ['-c'],
            });
        } catch (err) {
            reject(err);
            return;
        }
        const lines: string[] = [];
        let stdoutBytes = 0;
        const timer = setTimeout(() => {
            settle(() => {
                try {
                    shell.kill();
                } catch {
                    // Already exited; the close handler settles below.
                }
                reject(new Error('Bridge timed out'));
            });
        }, BRIDGE_TIMEOUT_MS);
        shell.on('message', (message: string) => {
            stdoutBytes += Buffer.byteLength(message, 'utf8');
            if (stdoutBytes > MAX_BRIDGE_STDOUT_BYTES) {
                settle(() => {
                    try {
                        shell.kill();
                    } catch {
                        // Already exited; the close handler settles below.
                    }
                    reject(new Error('Bridge output exceeded the transport limit'));
                });
                return;
            }
            lines.push(message);
        });
        try {
            // Send before end: end() closes stdin, so ending first would
            // fail the send with write-after-end and drop the payload.
            shell.send(input);
            shell.end((err: Error | null) => {
                settle(() => {
                    if (err) {
                        reject(err);
                        return;
                    }
                    resolve(lines);
                });
            });
        } catch (err) {
            settle(() => reject(err));
        }
    });
}

/**
 * Core finance verifier for NPV, IRR, and loan calculations
 */
export class FinanceVerifier {
    private pythonPath: string;

    constructor(pythonPath: string = 'python') {
        this.pythonPath = pythonPath;
    }

    /**
     * Verify NPV calculation
     */
    async verifyNPV(
        cashflows: number[],
        rate: number,
        llmOutput: string
    ): Promise<VerificationResult> {
        if (!Array.isArray(cashflows)) {
            throw new TypeError('cashflows must be an array of finite numbers');
        }
        const checkedRate = assertFiniteNumber(rate, 'rate');
        const checkedFlows = cashflows.map((flow, index) =>
            assertFiniteNumber(flow, `cashflows[${index}]`)
        );
        assertNonEmptyString(llmOutput, 'llmOutput', 65536);

        // The claim travels with the facts: the bridge compares it against
        // the recomputed NPV (FinanceVerifier.verify_npv) instead of
        // returning a computation-only verdict.
        const body = await this.runBridge(VERIFY_NPV_SCRIPT, {
            cashflows: checkedFlows,
            rate: checkedRate,
            llm_output: llmOutput,
        });
        if (typeof body['verified'] !== 'boolean') {
            throw new Error('NPV bridge returned a malformed verdict envelope');
        }
        return {
            verified: body['verified'] as boolean,
            computed_value: typeof body['computed_value'] === 'string'
                ? (body['computed_value'] as string)
                : undefined,
            receipt_id: typeof body['receipt_id'] === 'string'
                ? (body['receipt_id'] as string)
                : undefined,
            input_hash: typeof body['input_hash'] === 'string'
                ? (body['input_hash'] as string)
                : undefined,
        };
    }

    /**
     * Verify loan payment calculation
     */
    async verifyLoanPayment(
        principal: number,
        annualRate: number,
        months: number
    ): Promise<VerificationResult> {
        const checkedPrincipal = assertFiniteNumber(principal, 'principal');
        const checkedRate = assertFiniteNumber(annualRate, 'annualRate');
        const checkedMonths = assertFiniteNumber(months, 'months');
        if (!Number.isInteger(checkedMonths) || checkedMonths < 1) {
            throw new RangeError('months must be a positive integer');
        }

        const body = await this.runBridge(VERIFY_LOAN_SCRIPT, {
            principal: checkedPrincipal,
            annual_rate: checkedRate,
            months: checkedMonths,
        });
        if (typeof body['verified'] !== 'boolean') {
            throw new Error('Loan bridge returned a malformed verdict envelope');
        }
        return {
            verified: body['verified'] as boolean,
            computed_value: typeof body['computed_value'] === 'string'
                ? (body['computed_value'] as string)
                : undefined,
            receipt_id: typeof body['receipt_id'] === 'string'
                ? (body['receipt_id'] as string)
                : undefined,
        };
    }

    /**
     * Execute a static bridge script with a JSON stdin payload.
     * Rejects on transport failure, empty output, or unparseable output —
     * callers must treat rejection as "not verified" (fail closed).
     */
    private async runBridge(
        script: string,
        payload: Record<string, unknown>
    ): Promise<Record<string, unknown>> {
        const lines = await runBridgeScript(this.pythonPath, script, payload);
        const body = firstJsonObject(lines);
        if (body === null) {
            throw new Error('Bridge produced no parseable verdict envelope');
        }
        return body;
    }
}

/**
 * Compliance guard for AML/KYC checks
 */
export class ComplianceGuard {
    private pythonPath: string;

    constructor(pythonPath: string = 'python') {
        this.pythonPath = pythonPath;
    }

    /**
     * Check AML compliance
     */
    async checkAML(
        amount: number,
        countryCode: string
    ): Promise<AMLResult> {
        const checkedAmount = assertFiniteNumber(amount, 'amount');
        const checkedCountry = assertCountryCode(countryCode);

        const lines = await runBridgeScript(this.pythonPath, CHECK_AML_SCRIPT, {
            amount: checkedAmount,
            country_code: checkedCountry,
        });
        const body = firstJsonObject(lines);
        if (
            body === null ||
            typeof body['needs_flagging'] !== 'boolean' ||
            typeof body['reason'] !== 'string' ||
            typeof body['verified'] !== 'boolean'
        ) {
            throw new Error('AML bridge returned a malformed verdict envelope');
        }
        return {
            needs_flagging: body['needs_flagging'] as boolean,
            reason: body['reason'] as string,
            verified: body['verified'] as boolean,
        };
    }
}

/**
 * UCP integration for payment verification
 */
export class UCPVerifier {
    private pythonPath: string;

    constructor(pythonPath: string = 'python') {
        this.pythonPath = pythonPath;
    }

    /**
     * Verify a payment token
     */
    async verifyPaymentToken(tokenData: {
        amount: number;
        currency: string;
        customer_country: string;
        kyc_verified: boolean;
    }): Promise<PaymentVerificationResult> {
        if (!isRecord(tokenData)) {
            throw new TypeError('tokenData must be an object');
        }
        const checkedAmount = assertFiniteNumber(tokenData['amount'], 'tokenData.amount');
        const checkedCurrency = assertNonEmptyString(tokenData['currency'], 'tokenData.currency', 16);
        // Same ISO normalization as checkAML: Python compares
        // country_code.upper() against the high-risk set with no trim,
        // so ' YE ' would miss the set and bypass the flag rule.
        const checkedCountry = assertCountryCode(tokenData['customer_country']);
        if (typeof tokenData['kyc_verified'] !== 'boolean') {
            throw new TypeError('tokenData.kyc_verified must be a boolean');
        }

        const lines = await runBridgeScript(this.pythonPath, VERIFY_TOKEN_SCRIPT, {
            token: {
                amount: checkedAmount,
                currency: checkedCurrency,
                customer_country: checkedCountry,
                kyc_verified: tokenData['kyc_verified'],
            },
        });
        const body = firstJsonObject(lines);
        const receiptIds: unknown = body?.['receipt_ids'];
        const violations: unknown = body?.['violations'];
        if (
            body === null ||
            typeof body['can_proceed'] !== 'boolean' ||
            (body['status'] !== 'approved' &&
                body['status'] !== 'blocked' &&
                body['status'] !== 'pending_review') ||
            !Array.isArray(violations) ||
            !violations.every((entry: unknown) => typeof entry === 'string') ||
            !Array.isArray(receiptIds) ||
            !receiptIds.every((id: unknown) => typeof id === 'string')
        ) {
            throw new Error('Token bridge returned a malformed verdict envelope');
        }
        return {
            can_proceed: body['can_proceed'] as boolean,
            status: body['status'] as 'approved' | 'blocked' | 'pending_review',
            violations: violations as string[],
            receipt_ids: receiptIds as string[],
        };
    }
}

export default {
    FinanceVerifier,
    ComplianceGuard,
    UCPVerifier
};
