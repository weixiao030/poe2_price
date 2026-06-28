using System.Security.Cryptography;
using System.Text;

internal static class Program
{
    private const int SaltSize = 16;
    private const int NonceSize = 12;
    private const int TagSize = 16;
    private static readonly byte[] KeySeed = Encoding.UTF8.GetBytes("poe2-price-patch-launcher-v1");

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length == 3 && string.Equals(args[0], "--verify", StringComparison.OrdinalIgnoreCase))
            {
                return Verify(args[1], args[2]);
            }

            if (args.Length != 2)
            {
                Console.Error.WriteLine("Usage: PayloadPacker <payload.zip> <payload.enc>");
                Console.Error.WriteLine("       PayloadPacker --verify <payload.zip> <payload.enc>");
                return 2;
            }

            Pack(args[0], args[1]);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    private static void Pack(string payloadZipPath, string payloadEncPath)
    {
        var inputPath = Path.GetFullPath(payloadZipPath);
        var outputPath = Path.GetFullPath(payloadEncPath);
        if (!File.Exists(inputPath))
        {
            throw new FileNotFoundException("Payload zip was not found.", inputPath);
        }

        var outputDir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrWhiteSpace(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        var encrypted = Encrypt(File.ReadAllBytes(inputPath));
        File.WriteAllBytes(outputPath, encrypted);

        Console.WriteLine(outputPath);
    }

    private static int Verify(string payloadZipPath, string payloadEncPath)
    {
        var zipPath = Path.GetFullPath(payloadZipPath);
        var encPath = Path.GetFullPath(payloadEncPath);
        if (!File.Exists(zipPath))
        {
            throw new FileNotFoundException("Payload zip was not found.", zipPath);
        }

        if (!File.Exists(encPath))
        {
            throw new FileNotFoundException("Encrypted payload was not found.", encPath);
        }

        var plain = File.ReadAllBytes(zipPath);
        var decrypted = Decrypt(File.ReadAllBytes(encPath));
        if (!plain.SequenceEqual(decrypted))
        {
            throw new InvalidDataException("Encrypted payload does not match payload zip.");
        }

        Console.WriteLine("Verified encrypted payload.");
        return 0;
    }

    private static byte[] Encrypt(byte[] plain)
    {
        var salt = RandomNumberGenerator.GetBytes(SaltSize);
        var nonce = RandomNumberGenerator.GetBytes(NonceSize);
        var cipher = new byte[plain.Length];
        var tag = new byte[TagSize];

        using var aes = CreateAes(salt);
        aes.Encrypt(nonce, plain, cipher, tag);

        var encrypted = new byte[SaltSize + NonceSize + cipher.Length + TagSize];
        salt.CopyTo(encrypted, 0);
        nonce.CopyTo(encrypted, SaltSize);
        cipher.CopyTo(encrypted, SaltSize + NonceSize);
        tag.CopyTo(encrypted, SaltSize + NonceSize + cipher.Length);
        return encrypted;
    }

    private static byte[] Decrypt(byte[] encrypted)
    {
        if (encrypted.Length < SaltSize + NonceSize + TagSize)
        {
            throw new InvalidDataException("Encrypted payload is too short.");
        }

        var cipherSize = encrypted.Length - SaltSize - NonceSize - TagSize;
        var salt = encrypted.AsSpan(0, SaltSize).ToArray();
        var nonce = encrypted.AsSpan(SaltSize, NonceSize);
        var cipher = encrypted.AsSpan(SaltSize + NonceSize, cipherSize);
        var tag = encrypted.AsSpan(SaltSize + NonceSize + cipherSize, TagSize);
        var plain = new byte[cipherSize];

        using var aes = CreateAes(salt);
        aes.Decrypt(nonce, cipher, tag, plain);
        return plain;
    }

    private static AesGcm CreateAes(byte[] salt)
    {
        using var derive = new Rfc2898DeriveBytes(KeySeed, salt, 120_000, HashAlgorithmName.SHA256);
        return new AesGcm(derive.GetBytes(32), TagSize);
    }
}
