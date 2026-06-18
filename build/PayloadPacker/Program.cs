using System.Security.Cryptography;
using System.Text;

internal static class Program
{
    private static readonly byte[] KeySeed = Encoding.UTF8.GetBytes("poe2-price-patch-launcher-v1");

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 2)
            {
                Console.Error.WriteLine("Usage: PayloadPacker <payload.zip> <payload.enc>");
                return 2;
            }

            var inputPath = Path.GetFullPath(args[0]);
            var outputPath = Path.GetFullPath(args[1]);
            if (!File.Exists(inputPath))
            {
                throw new FileNotFoundException("Payload zip was not found.", inputPath);
            }

            var outputDir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(outputDir))
            {
                Directory.CreateDirectory(outputDir);
            }

            var plain = File.ReadAllBytes(inputPath);
            var salt = RandomNumberGenerator.GetBytes(16);
            var nonce = RandomNumberGenerator.GetBytes(12);
            var cipher = new byte[plain.Length];
            var tag = new byte[16];

            using var derive = new Rfc2898DeriveBytes(KeySeed, salt, 120_000, HashAlgorithmName.SHA256);
            var key = derive.GetBytes(32);
            using var aes = new AesGcm(key, 16);
            aes.Encrypt(nonce, plain, cipher, tag);

            using var output = File.Create(outputPath);
            output.Write(salt);
            output.Write(nonce);
            output.Write(cipher);
            output.Write(tag);

            Console.WriteLine(outputPath);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }
}
