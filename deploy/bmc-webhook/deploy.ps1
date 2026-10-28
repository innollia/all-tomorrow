$ErrorActionPreference = "Continue"
$here = $PSScriptRoot; $R = "ap-northeast-2"; $N = "bmc-webhook"; $AT = "$HOME\.all-tomorrow"
function Rand { -join ((1..40) | % { "{0:x}" -f (Get-Random -Max 16) }) }
$pullF = "$AT\bmc-pull.token"; if (-not (Test-Path $pullF)) { Set-Content -NoNewline -Encoding ascii $pullF (Rand) }
$secF = "$AT\bmc-webhook.secret"; $tmpF = "$here\temp.secret"
if (Test-Path $secF) { $sec = (Get-Content $secF -Raw).Trim(); "secret: user file" } else { if (-not (Test-Path $tmpF)) { Set-Content -NoNewline -Encoding ascii $tmpF (Rand) }; $sec = (Get-Content $tmpF -Raw).Trim(); "secret: TEMP" }
$pull = (Get-Content $pullF -Raw).Trim()

aws dynamodb describe-table --table-name $N --region $R --query Table.TableStatus --output text 2>$null
if (-not $?) { aws dynamodb create-table --table-name $N --region $R --attribute-definitions AttributeName=id,AttributeType=S --key-schema AttributeName=id,KeyType=HASH --billing-mode PAY_PER_REQUEST --query TableDescription.TableArn --output text; aws dynamodb wait table-exists --table-name $N --region $R }
$tableArn = aws dynamodb describe-table --table-name $N --region $R --query Table.TableArn --output text

$roleArn = aws iam get-role --role-name "$N-role" --query Role.Arn --output text 2>$null
if (-not $?) {
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' | Set-Content -Encoding ascii "$here\trust.json"
  $roleArn = aws iam create-role --role-name "$N-role" --assume-role-policy-document "file://$here\trust.json" --query Role.Arn --output text
  aws iam attach-role-policy --role-name "$N-role" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  Start-Sleep 10
}
"{`"Version`":`"2012-10-17`",`"Statement`":[{`"Effect`":`"Allow`",`"Action`":[`"dynamodb:PutItem`",`"dynamodb:DeleteItem`",`"dynamodb:Scan`"],`"Resource`":`"$tableArn`"}]}" | Set-Content -Encoding ascii "$here\ddb.json"
aws iam put-role-policy --role-name "$N-role" --policy-name ddb --policy-document "file://$here\ddb.json"

Compress-Archive -Force "$here\lambda_function.py" "$here\fn.zip"
@{ Variables = @{ TABLE = $N; PULL_TOKEN = $pull; BMC_WEBHOOK_SECRET = $sec } } | ConvertTo-Json -Compress | Set-Content -Encoding ascii "$here\env.json"
aws lambda get-function --function-name $N --region $R --query Configuration.State --output text 2>$null
if (-not $?) {
  aws lambda create-function --function-name $N --region $R --runtime python3.12 --handler lambda_function.lambda_handler --role $roleArn --zip-file "fileb://$here\fn.zip" --timeout 10 --memory-size 128 --environment "file://$here\env.json" --query State --output text
  aws lambda wait function-active --function-name $N --region $R
  aws lambda create-function-url-config --function-name $N --region $R --auth-type NONE --query FunctionUrl --output text
  aws lambda add-permission --function-name $N --region $R --statement-id url --action lambda:InvokeFunctionUrl --principal "*" --function-url-auth-type NONE --output text | Out-Null
  aws lambda add-permission --function-name $N --region $R --statement-id url-invoke --action lambda:InvokeFunction --principal "*" --invoked-via-function-url --output text 2>$null | Out-Null
} else {
  aws lambda update-function-code --function-name $N --region $R --zip-file "fileb://$here\fn.zip" --query LastUpdateStatus --output text
  aws lambda wait function-updated --function-name $N --region $R
  aws lambda update-function-configuration --function-name $N --region $R --environment "file://$here\env.json" --query LastUpdateStatus --output text
  aws lambda wait function-updated --function-name $N --region $R
}
Remove-Item "$here\env.json"
$url = aws lambda get-function-url-config --function-name $N --region $R --query FunctionUrl --output text
"url: $url"
